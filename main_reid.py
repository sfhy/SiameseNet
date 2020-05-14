# encoding: utf-8
from primary_objects_factory import get_trainer
from utils.standard_actions import prepare_running


@prepare_running
def train(opt):
    reid_trainer = get_trainer(opt)

    if opt.evaluate:
        reid_trainer.evaluate_best()
        return

    reid_trainer.continue_train()


if __name__ == '__main__':
    import fire
    fire.Fire()
