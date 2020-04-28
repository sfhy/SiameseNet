# encoding: utf-8
import errno
import os
import os.path as osp
import re
import shutil
import sys

import numpy as np
import torch


class Logger(object):
    """
    Write console output to external text file.
    Code imported from https://github.com/Cysu/open-reid/blob/master/reid/utils/logging.py.
    """

    def __init__(self, fpath=None):
        self.console = sys.stdout
        self.file = None
        if fpath is not None:
            mkdir_if_missing(os.path.dirname(fpath))
            self.file = open(fpath, 'a')

    def __del__(self):
        self.close()

    def __enter__(self):
        pass

    def __exit__(self, *args):
        self.close()

    def write(self, msg):
        self.console.write(msg)
        if self.file is not None:
            self.file.write(msg)

    def flush(self):
        self.console.flush()
        if self.file is not None:
            self.file.flush()
            os.fsync(self.file.fileno())

    def close(self):
        self.console.close()
        if self.file is not None:
            self.file.close()


def mkdir_if_missing(dir_path):
    try:
        os.makedirs(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def save_checkpoint(state, is_best, exp_dir, epoch, prefix: str):
    if 'ep' in prefix:
        raise ValueError('prefix {0} can not contain "ep"!'.format(prefix))

    save_dir = osp.join(exp_dir, 'checkpoints')
    os.makedirs(save_dir, exist_ok=True)

    # delete previous checkpoints
    files_path = osp.join(save_dir, prefix + '*')
    os.system('rm {0}'.format(files_path))

    # save current checkpoint
    filename = '{0}_ep{1}.pth.tar'.format(prefix, epoch)
    fpath = osp.join(save_dir, filename)
    mkdir_if_missing(save_dir)
    torch.save(state, fpath)
    if is_best:
        shutil.copy(fpath, osp.join(save_dir, 'model_best.pth.tar'))


def parse_checkpoints(exp_dir):
    load_dir = osp.join(exp_dir, 'checkpoints')
    os.makedirs(load_dir, exist_ok=True)

    files = os.listdir(load_dir)
    files = [f for f in files if '.pth.tar' in f]
    if 'model_best.pth.tar' in files:
        files.remove('model_best.pth.tar')
    pattern = re.compile(r'(?<=^checkpoint_ep)\d+')  # look for numbers
    epochs = [pattern.findall(f) for f in files]
    epochs = [int(e[0]) for e in epochs if len(e) > 0]

    start_epoch = 0
    state_dict = None
    best_rank1 = -np.inf
    best_epoch = 0
    if len(epochs) > 0:
        start_epoch = max(epochs)
        params_file_name = 'checkpoint_ep{0}.pth.tar'.format(start_epoch)
        params_file_path = osp.join(load_dir, params_file_name)
        state_dict = torch.load(params_file_path)['state_dict']

        best_params_file_path = osp.join(load_dir, 'model_best.pth.tar')
        if os.path.exists(best_params_file_path):
            best_params = torch.load(best_params_file_path)
            best_rank1 = best_params['rank1']
            best_epoch = best_params['epoch']

    optimizer_state_dict = None
    if start_epoch > 0:
        optimizer_state_dict_path = os.path.join(load_dir,
                                                 'optimizer_checkpoint_ep'
                                                 + str(start_epoch)
                                                 + '.pth.tar')

        if os.path.exists(optimizer_state_dict_path):
            optimizer_state_dict = torch.load(optimizer_state_dict_path)['state_dict']

    return start_epoch, state_dict, best_epoch, best_rank1, optimizer_state_dict


