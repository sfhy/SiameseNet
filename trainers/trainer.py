# encoding: utf-8
import os
import random
import time
from pprint import pprint

import matplotlib.pyplot as plt
import numpy as np
import torch
from prettytable import PrettyTable
from sklearn import svm
from sklearn.metrics import confusion_matrix

from dataset.attributes import get_market_attributes
from utils.meters import AverageMeter
from utils.serialization import save_best_model, save_current_status, get_best_model
from utils.standard_actions import print_time
from utils.tensor_section_functions import slice_tensor, tensor_size, tensor_cuda, tensor_cpu


class _Trainer:
    def __init__(self, opt, train_loader, evaluator, optimzier, lr_strategy,
                 criterion, summary_writer, phase_num=1, done_epoch=0):
        self.opt = opt
        self.train_loader = train_loader
        self.evaluator = evaluator
        self.model = evaluator.model
        self.optimizer = optimzier
        self.lr_strategy = lr_strategy
        self.criterion = criterion
        self.summary_writer = summary_writer
        _, best_epoch, best_rank1 = get_best_model(opt.exp_dir)
        self.best_rank1 = best_rank1
        self.best_epoch = best_epoch
        self.phase_num = phase_num
        self.done_epoch = done_epoch

    @print_time
    def continue_train(self):
        while self.done_epoch < self.opt.max_epoch:
            self._train(self.done_epoch + 1)
            self.done_epoch += 1

        if self.opt.savefig:
            self.visualize_best()

    def _adapt_to_best(self):
        best_state_dict, best_epoch, best_rank1 = get_best_model(self.opt.exp_dir)
        self.model.module.load_state_dict(best_state_dict)
        return best_epoch, best_rank1

    @print_time
    def visualize_best(self):
        best_epoch, best_rank1 = self._adapt_to_best()
        print('visualization based on the best model (rank-1 {:.1%}, achieved at epoch {}).'
              .format(best_rank1, best_epoch))
        self.evaluator.visualize(re_ranking=self.opt.re_ranking, eval_flip=False)
        self.evaluator.visualize(re_ranking=self.opt.re_ranking, eval_flip=True)
        print('The whole process should be terminated.')

    def evaluate_best(self, eval_flip=None):
        best_epoch, best_rank1 = self._adapt_to_best()
        print('evaluation based on the best model (rank-1 {:.1%}, achieved at epoch {}).'
              .format(best_rank1, best_epoch))
        self.evaluate(eval_flip)
        print('The whole process should be terminated.')

    def _train(self, epoch):
        """Note: epoch should start with 1"""

        try:
            if epoch == self.opt.freeze_pretrained_untill:
                print('no longer freeze pretrained params (if there were any pretrained params)!')
                self.model.module.unlable_pretrained()
                self.optimizer = self.model.module.get_optimizer(optim=self.opt.optim,
                                                                 lr=self.opt.lr,
                                                                 momentum=self.opt.momentum,
                                                                 weight_decay=self.opt.weight_decay)
        except AttributeError:
            print('the net does not have \'unlable_pretrained\' method')

        start = time.time()
        self.model.train()
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()
        self.lr_strategy(self.optimizer, epoch)
        for i, inputs in enumerate(self.train_loader):
            data_time.update(time.time() - start)
            # model optimizer
            self._parse_data(inputs)
            self._forward()
            self.optimizer.zero_grad()
            self._backward()
            self.optimizer.step()

            losses.update(self.loss.item())

            # tensorboard
            global_step = (epoch - 1) * len(self.train_loader) + i
            self.summary_writer.add_scalar('loss', self.loss.item(), global_step)
            self.summary_writer.add_scalar('lr', self.optimizer.param_groups[0]['lr'], global_step)

            if (i + 1) % self.opt.print_freq == 0:
                print('Epoch: [{}][{}/{}]\t'
                      'Batch Time {:.3f} ({:.3f})\t'
                      'Data Time {:.3f} ({:.3f})\t'
                      'Loss {:.3f} ({:.3f})\t'
                      .format(epoch, i + 1, len(self.train_loader),
                              batch_time.val, batch_time.mean,
                              data_time.val, data_time.mean,
                              losses.val, losses.mean))

            batch_time.update(time.time() - start)
            start = time.time()

        param_group = self.optimizer.param_groups
        print('Epoch: [{}]\tEpoch Time {:.3f} s\tLoss {:.6f}\t'
              'Lr {:.2e}'
              .format(epoch, batch_time.sum, losses.mean, param_group[0]['lr']))

        if self.opt.eval_step > 0 and epoch % self.opt.eval_step == 0 or epoch == self.opt.max_epoch:
            rank1 = self.evaluate(eval_flip=False)

            if rank1 > self.best_rank1:
                save_best_model(self.model, exp_dir=self.opt.exp_dir, epoch=epoch, rank1=rank1)
                self.best_rank1 = rank1
                self.best_epoch = epoch

        save_current_status(self.model, self.optimizer, self.opt.exp_dir, epoch, self.opt.eval_step)

    @print_time
    def evaluate(self, eval_flip=None):
        if eval_flip is None:
            self.evaluator.evaluate(re_ranking=self.opt.re_ranking, eval_flip=False)
            self.evaluator.evaluate(re_ranking=self.opt.re_ranking, eval_flip=True)
        else:
            rank1 = self.evaluator.evaluate(re_ranking=self.opt.re_ranking, eval_flip=eval_flip)
            return rank1

    def _get_feature_with_id(self, dataloader):
        self.model.eval()
        with torch.no_grad():
            mode = 'half' if self.opt.model_name in ['aabraidosnet', ] else 'extract'
            fun = lambda d: self.model(d, None, mode=mode)
            records = [(tensor_cpu(fun(tensor_cuda(data))), identity) for data, identity, _ in dataloader]

            features = []
            ids = []
            for features_, ids_ in records:
                features_ = features_.tolist()
                ids_ = [str(i.item()) for i in ids_]
                for id_, feature_ in zip(ids_, features_):
                    if id_ == '0':
                        continue
                    features.append(feature_)
                    ids.append(id_)

        # shuffle
        num = len(ids)
        indices = [i for i in range(num)]
        random.shuffle(indices)
        features = [features[i] for i in indices]
        ids = [ids[i] for i in indices]

        return np.array(features), ids

    @print_time
    def check_discriminant_best(self, set_name='train'):
        if self.opt.dataset is not 'market1501':
            raise NotImplementedError

        best_epoch, best_rank1 = self._adapt_to_best()
        print('check discriminant based on the best model (rank-1 {:.1%}, achieved at epoch {}).'
              .format(best_rank1, best_epoch))

        if set_name == 'train':
            data_loader = self.train_loader
        elif set_name == 'test':
            data_loader = self.evaluator.queryloader  # has already been merged with galleryloader
        features, ids = self._get_feature_with_id(data_loader)

        sample_num = len(features)
        split_border = sample_num // 2 + 1
        features_train = features[:split_border]
        features_test = features[split_border:]

        attributes, label2word = get_market_attributes(set_name=set_name)

        attribute_ids = attributes.pop('image_index')
        index_map = [attribute_ids.index(i) for i in ids]

        attributes_new = dict()
        for key, label in attributes.items():
            label_new = [label[i] for i in index_map]
            attributes_new[key] = np.array(label_new)

        field_names = ('Attribute', 'Accuracy', 'The Worst Precision')
        table = PrettyTable(field_names=field_names)

        x = []
        y = []
        for key, labels in attributes_new.items():
            labels_train = labels[:split_border]
            labels_test = labels[split_border:]
            classes = set(labels)
            for class_ in classes:
                if len(classes) == 2 and class_ == 1:
                    continue
                # print('checking the discriminant for the label {0} of {1}'.format(class_, key))
                print('checking the discriminant for {0} ...'.format(label2word[key][class_]))
                hitted_train = (labels_train == class_).astype(int)
                hitted_test = (labels_test == class_).astype(int)

                model = svm.SVC(kernel='linear')
                try:
                    model.fit(features_train, hitted_train)
                except ValueError:
                    print('skip it due to missing pos/neg samples')
                    print()
                    continue
                prediction = model.predict(features_test)

                cm = confusion_matrix(y_pred=prediction, y_true=hitted_test)
                accuracy = float(cm[1, 1] + cm[0, 0]) / float(cm[0, 0] + cm[0, 1] + cm[1, 1] + cm[1, 0])
                precision_pos = float(cm[1, 1]) / float(cm[1, 1] + cm[1, 0])
                precision_neg = float(cm[0, 0]) / float(cm[0, 0] + cm[0, 1])
                worst_precision = min(precision_pos, precision_neg)

                table.add_row([label2word[key][class_],
                               '{0:.3%}'.format(accuracy),
                               '{0:.3%}'.format(worst_precision)])

                x.append(label2word[key][class_])
                y.append(worst_precision * 100)

                print('accuracy: {0:.3%}'.format(accuracy))
                print('worst_precision: {0:.3%}'.format(worst_precision))
                print('confusion matrix:')
                pprint(cm)
                print()

        print(table)

        # fig, ax = plt.subplots()

        plt.bar(x, y, width=0.2)
        plt.xticks(x, x, rotation=90)
        plt.xlabel('Attribute', fontsize=14)
        plt.ylabel('The Worst Precision (%)', fontsize=14)
        plt.ylim(0., 100.)
        params = {'figure.figsize': '24, 6'}
        plt.rcParams.update(params)

        plt.tight_layout()

        # plt.subplots_adjust(left=0.1, right=0.9, bottom=0.1, top=0.9)

        save_dir = os.path.join(self.opt.exp_dir, 'visualize')
        os.makedirs(save_dir, exist_ok=True)

        plt.savefig(os.path.join(save_dir, '{0}_DA_{1}.png'.format(self.opt.exp_name, set_name)))
        plt.close()

        print('The whole process should be terminated.')

    @print_time
    def check_element_discriminant_best(self, set_name='train'):
        if self.opt.dataset is not 'market1501':
            raise NotImplementedError

        best_epoch, best_rank1 = self._adapt_to_best()
        print('check element discriminant based on the best model (rank-1 {:.1%}, achieved at epoch {}).'
              .format(best_rank1, best_epoch))

        if set_name == 'train':
            data_loader = self.train_loader
        elif set_name == 'test':
            data_loader = self.evaluator.queryloader  # has already been merged with galleryloader
        features, ids = self._get_feature_with_id(data_loader)

        sample_num = len(features)
        split_border = sample_num // 2 + 1
        features_train = features[:split_border]
        features_test = features[split_border:]

        attributes, label2word = get_market_attributes(set_name=set_name)

        attribute_ids = attributes.pop('image_index')
        index_map = [attribute_ids.index(i) for i in ids]

        attributes_new = dict()
        for key, label in attributes.items():
            label_new = [label[i] for i in index_map]
            attributes_new[key] = np.array(label_new)

        field_names = ('Attribute', 'The Best Worst Precision')
        table = PrettyTable(field_names=field_names)

        x = []
        y = []
        for key, labels in attributes_new.items():
            labels_train = labels[:split_border]
            labels_test = labels[split_border:]
            classes = set(labels)
            for class_ in classes:
                if len(classes) == 2 and class_ == 1:
                    continue
                # print('checking the discriminant for the label {0} of {1}'.format(class_, key))
                print('checking the discriminant for {0} ...'.format(label2word[key][class_]))
                hitted_train = (labels_train == class_).astype(int)
                hitted_test = (labels_test == class_).astype(int)
                if sum(hitted_train) == 0 or sum(hitted_train) == len(hitted_train):
                    print('skip it due to missing pos/neg samples')
                    print()
                    continue

                feature_length = features_train.shape[1]
                best_worst_precision = 0.
                for i in range(feature_length):
                    print('{0}/{1}'.format(i, feature_length))
                    features_train_one = features_train[i]
                    features_test_one = features_test[i]

                    model = svm.SVC(kernel='linear')
                    model.fit(features_train_one, hitted_train)
                    prediction = model.predict(features_test_one)

                    cm = confusion_matrix(y_pred=prediction, y_true=hitted_test)
                    precision_pos = float(cm[1, 1]) / float(cm[1, 1] + cm[1, 0])
                    precision_neg = float(cm[0, 0]) / float(cm[0, 0] + cm[0, 1])
                    worst_precision = min(precision_pos, precision_neg)

                    best_worst_precision = max(best_worst_precision, worst_precision)

                table.add_row([label2word[key][class_],
                               '{0:.3%}'.format(best_worst_precision)])

                x.append(label2word[key][class_])
                y.append(best_worst_precision * 100)

                print('best_worst_precision: {0:.3%}'.format(best_worst_precision))
                print()

        print(table)

        fig, ax = plt.subplots()

        plt.bar(x, y, width=0.2)
        plt.xticks(x, x, rotation=90)
        plt.xlabel('Attribute', fontsize=14)
        plt.ylabel('The Best Worst Precision (%)', fontsize=14)
        plt.ylim(0., 100.)
        params = {'figure.figsize': '24, 6'}
        plt.rcParams.update(params)

        fig.subplots_adjust(left=0.1, right=0.9, bottom=0.1, top=0.9)

        save_dir = os.path.join(self.opt.exp_dir, 'visualize')
        os.makedirs(save_dir, exist_ok=True)

        plt.savefig(os.path.join(save_dir, '{0}_EDA_{1}.png'.format(self.opt.exp_name, set_name)))
        plt.close()

        print('The whole process should be terminated.')

    def _parse_data(self, inputs):
        raise NotImplementedError

    def _forward(self):
        raise NotImplementedError

    def _backward(self):
        raise NotImplementedError

    def _extract_feature(self, data):
        raise NotImplementedError

    def _compare_feature(self, features):
        raise NotImplementedError


class BraidPairTrainer(_Trainer):
    def _parse_data(self, inputs):
        (imgs_a, pids_a, _), (imgs_b, pids_b, _) = inputs

        target = [1. if a == b else 0. for a, b in zip(pids_a, pids_b)]
        self.data = (imgs_a.cuda(), imgs_b.cuda())
        self.target = torch.tensor(target).cuda().unsqueeze(1)

    def _extract_feature(self, data):
        return self.model(data, mode='extract')

    def _compare_feature(self, *features):
        return self.model(*features, mode='metric')

    def _forward(self):
        if self.phase_num == 1:
            score = self.model(*self.data, mode='normal')

        elif self.phase_num == 2:
            feat_a = self._extract_feature(self.data[0])
            feat_b = self._extract_feature(self.data[1])
            score = self._compare_feature(feat_a, feat_b)

        else:
            raise ValueError

        self.loss = self.criterion(score, self.target)

    def _backward(self):
        self.loss.backward()
        self.model.module.correct_grads()


class BraidCrossTrainer(BraidPairTrainer):
    def _parse_data(self, inputs):
        imgs, pids, _ = inputs
        self.data = imgs.cuda()
        self.target = pids.cuda()

    def _compare_feature(self, features):
        # only compute the lower triangular of the distmat

        n = tensor_size(features, dim=0)
        a_indices, b_indices = torch.tril_indices(n, n)
        scores_l = self.model(slice_tensor(features, a_indices),
                              slice_tensor(features, b_indices),
                              mode='metric').squeeze()

        if len(scores_l.size()) == 1:
            score_mat = torch.zeros((n, n), device=scores_l.device, dtype=scores_l.dtype)
        elif len(scores_l.size()) == 2:
            score_mat = torch.zeros((n, n, scores_l.size()[1]), device=scores_l.device, dtype=scores_l.dtype)
        else:
            raise NotImplementedError

        score_mat[a_indices, b_indices] = scores_l
        score_mat[b_indices, a_indices] = scores_l

        return score_mat

    def _forward(self):
        if self.phase_num == 1:
            raise NotImplementedError('In most cases, it will waste too much computation.')

        elif self.phase_num == 2:
            features = self._extract_feature(self.data)
            score_mat = self._compare_feature(features)

        else:
            raise ValueError

        self.loss = self.criterion(score_mat, self.target)


class BraidCrossIDETrainer(BraidCrossTrainer):
    def __init__(self, *args, **kwargs):
        super(BraidCrossIDETrainer, self).__init__(*args, **kwargs)
        if not isinstance(self.criterion, (list, tuple)):
            raise ValueError

        if len(self.criterion) != 2:
            raise ValueError

        self.trade_off = self.opt.trade_off

    def _parse_data(self, inputs):
        imgs, pids, _ = inputs
        self.data = imgs.cuda()
        self.target = pids.cuda()

    def _forward(self):
        if self.phase_num == 1:
            raise NotImplementedError('In most cases, it will waste too much computation.')

        elif self.phase_num == 2:
            predics, features = self._extract_feature(self.data)
            score_mat = self._compare_feature(features)

        else:
            raise ValueError

        self.loss = self.trade_off * self.criterion[0](predics, self.target) \
                    + (1 - self.trade_off) * self.criterion[1](score_mat, self.target)


class NormalTrainer(_Trainer):
    def _parse_data(self, inputs):
        imgs, pids, _ = inputs
        self.data = imgs.cuda()
        self.target = pids.cuda()

    def _forward(self):
        if self.phase_num == 1:
            predictions = self._extract_feature(self.data)

        elif self.phase_num == 2:
            raise NotImplementedError

        else:
            raise ValueError

        self.loss = self.criterion(predictions, self.target)

    def _backward(self):
        self.loss.backward()

    def _extract_feature(self, data):
        return self.model(self.data, mode='extract')

    def _compare_feature(self, features):
        raise NotImplementedError
