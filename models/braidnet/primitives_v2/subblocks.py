import torch
import torch.nn as nn
from torch.nn import BatchNorm1d as BatchNorm1d
from torch.nn import BatchNorm2d as BatchNorm2d

__all__ = ['WConv2d', 'WLinear', 'WBatchNorm2d',
           'WBatchNorm1d', 'PartPool', 'ReLU']

POOLS_DICT = {'max': nn.AdaptiveMaxPool2d, 'avg': nn.AdaptiveAvgPool2d}


class WConv2d(nn.Module):
    def __init__(self, in_channels=10, out_channels=10, kernel_size=3, stride=(1, 1),
                 padding=(1, 1), dilation=1, groups=1, bias=True):
        super(WConv2d, self).__init__()
        if groups != 1:
            raise NotImplementedError

        self.conv_p = nn.Conv2d(in_channels, out_channels, kernel_size,
                                stride, padding, dilation, groups, bias)

        self.conv_q = nn.Conv2d(in_channels, out_channels, kernel_size,
                                stride, padding, dilation, groups, False)

    def forward(self, input_):
        in_a, in_b = input_
        out_a = self.conv_p(in_a) + self.conv_q(in_b)
        out_b = self.conv_p(in_b) + self.conv_q(in_a)
        return out_a, out_b

    def correct_params(self):
        self.conv_p.weight.data /= 2.
        self.conv_q.weight.data /= 2.


class WLinear(nn.Module):
    def __init__(self, in_features, out_features, bias=True):
        super(WLinear, self).__init__()
        self.conv_p = nn.Linear(in_features, out_features, bias)
        self.conv_q = nn.Linear(in_features, out_features, False)

    def forward(self, input_):
        in_a, in_b = input_
        out_a = self.conv_p(in_a) + self.conv_q(in_b)
        out_b = self.conv_p(in_b) + self.conv_q(in_a)
        return out_a, out_b

    def correct_params(self):
        self.conv_p.weight.data /= 2.
        self.conv_q.weight.data /= 2.


class WBatchNorm2d(nn.Module):
    def __init__(self, num_channels, eps=1e-5, **kwargs):
        super(WBatchNorm2d, self).__init__()
        self.bn = BatchNorm2d(num_features=num_channels, eps=eps, **kwargs)

    def forward(self, input_):
        in_a, in_b = input_
        input_ = torch.cat((in_a, in_b), dim=0)
        output_ = self.bn(input_)
        out_a, out_b = torch.chunk(output_, 2, dim=0)
        return out_a, out_b


class WBatchNorm1d(nn.Module):
    def __init__(self, num_channels, eps=1e-5, **kwargs):
        super(WBatchNorm1d, self).__init__()
        self.bn = BatchNorm1d(num_features=num_channels, eps=eps, **kwargs)

    def forward(self, input_):
        in_a, in_b = input_
        input_ = torch.cat((in_a, in_b), dim=0)
        output_ = self.bn(input_)
        out_a, out_b = torch.chunk(output_, 2, dim=0)
        return out_a, out_b


class PartPool(nn.Module):
    def __init__(self, part_num=1, method='max'):
        super(PartPool, self).__init__()
        self.pool = POOLS_DICT[method]((part_num, 1))

    def forward(self, input_):
        if isinstance(input_, (list, tuple)):
            return [self.pool(i) for i in input_]
        else:
            return self.pool(input_)


class ReLU(nn.Module):
    def __init__(self, *args, **kwargs):
        super(ReLU, self).__init__()
        self.relu = nn.ReLU(*args, **kwargs)

    def forward(self, input_):
        if isinstance(input_, (list, tuple)):
            return [self(i) for i in input_]
        else:
            return self.relu(input_)

# class PartPools(nn.Module):
#     def __init__(self, part_nums=(1, 2, 3), methods=('max', 'avg')):
#         super(PartPools, self).__init__()
#         self.part_nums = part_nums
#         self.methods = methods
#         self.pools = nn.ModuleList()
#         for part_num in part_nums:
#             n_pools = nn.ModuleList()
#             for m in methods:
#                 n_pools.append(POOLS_DICT[m]((part_num, 1)))
#
#             self.pools.append(n_pools)
#
#     def forward(self, input_):
#         result = []
#         for sub_pools in self.pools:
#             sub_result = []
#             for pool in sub_pools:
#                 sub_result.append(pool(input_))
#
#             # result.append(torch.cat(sub_result, 1))
#             result.append(sub_result)
#
#         return result
