from os.path import join as path_join

from tensorboardX import SummaryWriter

from .dataloader_generator import get_dataloaders
from .evaluator_generator import get_evaluator
from .lr_strategy_generator import get_lr_strategy
from .model_with_optimizer_generator import get_model_with_optimizer


def get_trainer(opt):
    model, optimizer, done_epoch = get_model_with_optimizer(opt)
    data_loaders = get_dataloaders(opt, model.module.meta)
    evaluator = get_evaluator(opt, model, **data_loaders)

    summary_writer = SummaryWriter(path_join(opt.exp_dir, 'tensorboard_log'))
    lr_strategy = get_lr_strategy(opt)

    if opt.train_mode == 'pair':
        if opt.loss == 'bce':
            from torch.nn import BCELoss
            criterion = BCELoss()

        else:
            raise NotImplementedError

        from trainers.trainer import BraidPairTrainer
        reid_trainer = BraidPairTrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy, criterion,
                                        summary_writer, opt.train_phase_num, done_epoch)

    elif opt.train_mode == 'cross':
        if opt.loss == 'bce':
            from utils.loss import CrossSimilarityBCELoss
            criterion = CrossSimilarityBCELoss()

        elif opt.loss == 'triplet':
            from utils.loss import TripletLoss4Braid
            criterion = TripletLoss4Braid(opt.margin)

        else:
            raise NotImplementedError

        from trainers.trainer import BraidCrossTrainer
        reid_trainer = BraidCrossTrainer(opt, data_loaders['trainloader'], evaluator, optimizer, lr_strategy, criterion,
                                         summary_writer, opt.train_phase_num, done_epoch)

    else:
        raise NotImplementedError

    return reid_trainer
