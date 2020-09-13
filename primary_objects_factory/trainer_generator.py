from os.path import join as path_join

from tensorboardX import SummaryWriter

from .dataloader_generator import get_dataloaders
from .evaluator_generator import get_evaluator
from .lr_strategy_generator import get_lr_strategy
from .model_with_optimizer_generator import get_model_with_optimizer


def get_trainer(opt):
    model = get_model_with_optimizer(opt, naive=True)
    data_loaders = get_dataloaders(opt, model.meta)
    _, train_ids, _ = zip(*data_loaders['trainloader'].dataset.dataset)
    train_id_num = len(set(train_ids))
    model, optimizer, done_epoch = get_model_with_optimizer(opt, id_num=train_id_num)

    evaluator = get_evaluator(opt, model, **data_loaders)

    summary_writer = SummaryWriter(path_join(opt.exp_dir, 'tensorboard_log'))
    lr_strategy = get_lr_strategy(opt)

    if opt.train_mode == 'pair':
        if opt.loss == 'bce':
            if opt.srl:
                print('Make Loss With Sample Rate Learning!')
                from SampleRateLearning.loss import SRL_BCELoss
                criterion = SRL_BCELoss(sampler=data_loaders['trainloader'].sampler,
                                        optim=opt.srl_optim,
                                        lr=opt.srl_lr,
                                        momentum=opt.srl_momentum,
                                        weight_decay=opt.srl_weight_decay)

            else:
                from utils.loss import PairSimilarityBCELoss
                criterion = PairSimilarityBCELoss()

        elif opt.loss == 'ce':
            from torch.nn import CrossEntropyLoss
            criterion = CrossEntropyLoss()

        else:
            raise NotImplementedError

        from trainers.trainer import BraidPairTrainer
        reid_trainer = BraidPairTrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy, criterion,
                                        summary_writer, opt.train_phase_num, done_epoch)

    elif opt.train_mode == 'cross':
        if opt.loss == 'bce':
            from utils.loss import CrossSimilarityBCELoss
            criterion = CrossSimilarityBCELoss()

        elif opt.loss == 'lbce':
            from utils.loss import CrossSimilarityLBCELoss
            criterion = CrossSimilarityLBCELoss()

        elif opt.loss == 'triplet':
            from utils.loss import TripletLoss4Braid
            criterion = TripletLoss4Braid(opt.margin)

        elif opt.loss == 'ce':
            from utils.loss import CrossSimilarityCELoss
            criterion = CrossSimilarityCELoss()

        else:
            raise NotImplementedError

        from trainers.trainer import BraidCrossTrainer
        reid_trainer = BraidCrossTrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy, criterion,
                                         summary_writer, opt.train_phase_num, done_epoch)

    elif opt.train_mode == 'ide_cross':
        if opt.loss == 'lsce_bce':
            from utils.loss import CrossEntropyLabelSmooth
            from utils.loss import CrossSimilarityBCELoss
            criterion = [CrossEntropyLabelSmooth(num_classes=train_id_num),
                         CrossSimilarityBCELoss()]

        else:
            raise NotImplementedError

        from trainers.trainer import BraidCrossIDETrainer
        reid_trainer = BraidCrossIDETrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy,
                                            criterion,
                                            summary_writer, opt.train_phase_num, done_epoch)

    elif opt.train_mode == 'normal':
        if opt.loss == 'lsce':
            from utils.loss import CrossEntropyLabelSmooth
            criterion = CrossEntropyLabelSmooth(num_classes=train_id_num)

        elif opt.loss == 'ce':
            from torch.nn import CrossEntropyLoss
            criterion = CrossEntropyLoss()

        else:
            raise NotImplementedError

        from trainers.trainer import NormalTrainer
        reid_trainer = NormalTrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy, criterion,
                                     summary_writer, opt.train_phase_num, done_epoch)

    else:
        raise NotImplementedError

    if opt.srl:
        from SampleRateLearning.serialization import parse_srl_checkpoints
        start_epoch, srl_state_dict = parse_srl_checkpoints(opt.exp_dir)
        if srl_state_dict is not None:
            print('SRL mechanism comes to the state after epoch {0}'.format(start_epoch))
            criterion.load_state_dict(srl_state_dict)

    return reid_trainer
