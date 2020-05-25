from torch.utils.data import DataLoader

from dataset import data_info
from dataset.data_image import ImageData
from dataset.transforms import TestTransform, TrainTransform


def get_dataloaders(opt, model_meta):
    print('initializing {} dataset ...'.format(opt.dataset))

    if isinstance(opt.dataset, list):
        dataset = data_info.init_united_datasets(names=opt.dataset, mode=opt.mode)
    else:
        dataset = data_info.init_dataset(name=opt.dataset, mode=opt.mode)

    if opt.test_pids_num >= 0:
        dataset.subtest2train(opt.test_pids_num)

    if opt.eval_fast:
        dataset.reduce_query()

    dataset.print_summary()

    pin_memory = True

    if opt.train_mode == 'normal' or opt.check_discriminant:
        trainloader = DataLoader(
            ImageData(dataset.train, TrainTransform(opt.datatype, model_meta, augmentaion=opt.augmentation)),
            batch_size=opt.train_batch, num_workers=opt.workers,
            pin_memory=pin_memory, drop_last=True, shuffle=True
        )

    elif opt.train_mode == 'pair':
        from dataset.samplers import PosNegPairSampler
        trainloader = DataLoader(
            ImageData(dataset.train, TrainTransform(opt.datatype, model_meta, augmentaion=opt.augmentation)),
            sampler=PosNegPairSampler(data_source=dataset.train,
                                      pos_rate=opt.pos_rate,
                                      sample_num_per_epoch=opt.iter_num_per_epoch * opt.train_batch),
            batch_size=opt.train_batch, num_workers=opt.workers,
            pin_memory=pin_memory, drop_last=False
        )

    elif opt.train_mode == 'cross':
        from dataset.samplers import RandomIdentitySampler
        trainloader = DataLoader(
            ImageData(dataset.train, TrainTransform(opt.datatype, model_meta, augmentaion=opt.augmentation)),
            sampler=RandomIdentitySampler(dataset.train, opt.num_instances),
            batch_size=opt.train_batch, num_workers=opt.workers,
            pin_memory=pin_memory, drop_last=True
        )

    else:
        raise NotImplementedError

    queryloader = DataLoader(
        ImageData(dataset.query, TestTransform(opt.datatype, model_meta)),
        batch_size=opt.test_batch, num_workers=opt.workers,
        pin_memory=pin_memory
    )

    galleryloader = DataLoader(
        ImageData(dataset.gallery, TestTransform(opt.datatype, model_meta)),
        batch_size=opt.test_batch, num_workers=opt.workers,
        pin_memory=pin_memory
    )

    queryFliploader = DataLoader(
        ImageData(dataset.query, TestTransform(opt.datatype, model_meta, True)),
        batch_size=opt.test_batch, num_workers=opt.workers,
        pin_memory=pin_memory
    )

    galleryFliploader = DataLoader(
        ImageData(dataset.gallery, TestTransform(opt.datatype, model_meta, True)),
        batch_size=opt.test_batch, num_workers=opt.workers,
        pin_memory=pin_memory
    )

    return {'trainloader': trainloader,
            'queryloader': queryloader,
            'galleryloader': galleryloader,
            'queryFliploader': queryFliploader,
            'galleryFliploader': galleryFliploader}
