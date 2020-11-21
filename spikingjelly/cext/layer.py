import torch
import torch.nn as nn
import torch.nn.functional as F
import spikingjelly.cext.functional

import math
import numpy as np
import time
class SparseLinear(nn.Linear):
    '''
    * :ref:`API in English <SparseLinear-en>`

    .. _SparseLinear-cn:

    :param in_features: 输入的特征数量
    :type in_features: int
    :param out_features: 输出的特征数量
    :type out_features: int
    :param bias: 若为 ``False``，则本层不含有可学习的偏置项。默认为 ``True``
    :type bias: bool

    适用于稀疏输入的全连接层。与 ``torch.nn.Linear`` 的行为几乎相同。

    .. warning::

        代码内部的实现方式是，首先将 ``sparse`` 转换为稀疏矩阵格式，然后再调用相关库进行运算。如果 ``sparse`` 不够稀疏，则该函数的速度会比普通矩阵乘法 ``torch.mm`` 慢很多。

    .. warning::

        稀疏矩阵的乘法存在一定的计算误差，但误差并不显著，或可忽略。

    * :ref:`中文API <SparseLinear-cn>`

    .. _SparseLinear-en:

    :param in_features: size of each input sample
    :type in_features: int
    :param out_features: size of each output sample
    :type out_features: int
    :param bias: If set to ``False``, the layer will not learn an additive bias.
        Default: ``True``
    :type bias: bool

    The fully connected layer for sparse inputs. This module has a similar behavior as ``torch.nn.Linear``.

    .. admonition:: Warning
        :class: warning

        This function is implemented by converting ``sparse`` to a sparse format and doing a sparse matrix multiplication.
        If the sparsity of ``sparse`` is not high enough, the speed of this function will be slower than ``torch.mm``.

    .. admonition:: Warning
        :class: warning

        There are some numeral errors when doing the sparse matrix multiplication. But the errors are not significant.
    '''
    def forward(self, sparse: torch.Tensor) -> torch.Tensor:
        if self.bias is None:
            return spikingjelly.cext.functional.sparse_mm_dense(sparse, self.weight.t())
        else:
            return spikingjelly.cext.functional.sparse_mm_dense(sparse, self.weight.t()) + self.bias

class AutoSparseLinear(nn.Linear):
    def __init__(self, in_features: int, out_features: int, bias: bool = True, in_spikes: bool = False):
        '''
        * :ref:`API in English <AutoSparseLinear-en>`

        .. _AutoSparseLinear-cn:

        :param in_features: 输入的特征数量
        :type in_features: int
        :param out_features: 输出的特征数量
        :type out_features: int
        :param bias: 若为 ``False``，则本层不含有可学习的偏置项。默认为 ``True``
        :type bias: bool
        :param in_spikes: 输入是否为脉冲，即元素均为0或1
        :type in_spikes: bool

        智能稀疏全连接层。对于任意输入，若它的 ``batch_size`` 对应的临界稀疏度未知，本层会首先运行基准测试 :ref:`AutoSparseLinear.benchmark <AutoSparseLinear.benchmark-cn>` 来获取临界稀疏度。临界稀疏度定义为，当输入是这一稀疏度时，稀疏矩阵乘法和普通矩阵乘法的速度恰好相同。对于任意输入，若它的 ``batch_size`` 对应的临界稀疏度已知，本层都会根据当前输入的稀疏度来智能决定是使用稀疏矩阵乘法还是普通矩阵乘法。

        .. warning::

            稀疏矩阵的乘法存在一定的计算误差，但误差并不显著，或可忽略。

        * :ref:`中文API <AutoSparseLinear-cn>`

        .. _AutoSparseLinear-en:

        :param in_features: size of each input sample
        :type in_features: int
        :param out_features: size of each output sample
        :type out_features: int
        :param bias: If set to ``False``, the layer will not learn an additive bias.
            Default: ``True``
        :type bias: bool
        :param in_spikes: Whether inputs are spikes, whose elements are 0 and 1
            Default: ``False``
        :type in_spikes: bool

        The auto sparse fully connected layer. For an input, if the corresponding critical sparsity of the input's batch
        size is unknown, this layer will firstly run the benchmark :ref:`AutoSparseLinear.benchmark <AutoSparseLinear.benchmark-en>` to get the critical sparsity. The critical sparsity is the sparsity where the sparse matrix multiplication and the dense matrix multiplication have the same speed. For an input, if the corresponding critical sparsity of the input's batch size is known, this layer can auto select whether using the sparse or dense matrix multiplication according to the current input's sparsity.

        .. admonition:: Warning
            :class: warning

            There are some numeral errors when doing the sparse matrix multiplication. But the errors are not significant.
        '''
        super().__init__(in_features, out_features, bias)
        self.critical_sparsity = {}  
        # 键是输入数据的batch_size，值是临界稀疏度
        # 当稀疏度高于临界稀疏度，前向传播使用稀疏矩阵乘法；否则使用普通矩阵乘法
        self.in_spikes = in_spikes

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size = x.shape[0]
        if batch_size not in self.critical_sparsity:
            return F.linear(x, self.weight, self.bias)

        else:
            with torch.no_grad():
                if self.in_spikes:
                    sparsity = 1 - x.mean().item()
                else:
                    sparsity = (x == 0).mean().item()
        if sparsity < self.critical_sparsity[batch_size]:
            return F.linear(x, self.weight, self.bias)
        else:
            if self.bias is None:
                return spikingjelly.cext.functional.sparse_mm_dense(x, self.weight)
            else:
                return spikingjelly.cext.functional.sparse_mm_dense(x, self.weight) + self.bias    

    def extra_repr(self) -> str:
        return f'in_features={self.in_features}, out_features={self.out_features}, bias={self.bias is not None}, critical_sparsity={self.critical_sparsity}'

    def benchmark(self, batch_size: int, device=None, run_times=1024, precision=1e-4, verbose=False):
        '''
        * :ref:`API in English <AutoSparseLinear.benchmark-en>`

        .. _AutoSparseLinear.benchmark-cn:

        :param batch_size: 输入的batch size
        :type batch_size: int
        :param device: 运行基准测试所在的设备。若为 ``None``，则会被设置成本层所在的设备。
        :type device: str or None
        :param run_times: 运行稀疏/普通矩阵乘法的重复实验的次数。越大，则基准测试的结果越可靠
        :type run_times: int
        :param precision: 二分搜索的最终临界稀疏值的精度
        :type precision: float
        :param verbose: 是否打印出测试过程中的日志
        :type verbose: bool

        使用二分查找，在输入的batch size为 ``batch_size`` 时，在每个稀疏度上重复运行 ``run_times`` 次稀疏/普通矩阵乘法，比较
        两者的速度，直到搜索到临界稀疏度。若搜索达到精度范围 ``precision`` 时，普通矩阵乘法仍然比稀疏矩阵乘法快，则会将临界稀疏度设
        置成 ``None``。

        * :ref:`中文API <AutoSparseLinear.benchmark-cn>`

        .. _AutoSparseLinear.benchmark-en:

        :param batch_size: batch size of the input
        :type batch_size: int
        :param device: where to running the benchmark. If ``None``, it will be set as same with this layer's device
        :type device: str
        :param run_times: the number of replicated running times for sparse/dense matrix multiplication. The benchmark
            result will be more reliable with a larger ``run_times``
        :type run_times: int
        :param precision: the precision of binary searching critical sparsity
        :type precision: float
        :param verbose: If ``True``, this function will print logs during running
        :type verbose: bool

        Using the binary search to find the critical sparsity when the batch size of the input is ``batch_size``. This function
        will run ``run_times`` sparse/dense matrix multiplication on different sparsity and compare their speeds until it
        finds the cirtical sparsity. If the dense matrix multiplication is faster than the sparse matrix multiplication
        when searching exceeds ``precision``, then the critical sparsity will be set to ``None``.

        '''
        if self.critical_sparsity.__len__() > 4:
            print('AutoSparseLinear: Warning: The batch size of the input has changed more than 4 times. AutoSparseLinear may waste too much time on running benchmark.')
        if verbose:
            print('AutoSparseLinear is running benchmark...')
        if device is None:
            device = self.weight.device
        
        if self.bias is None:
            bias = False
        else:
            bias = True
        
        fc_sparse = SparseLinear(self.in_features, self.out_features, bias)
        fc_sparse.to(device)
        fc_dense = nn.Linear(self.in_features, self.out_features, bias)
        fc_dense.to(device)

        sparsity_r = 1.0
        sparsity_l = 0.9
        # 二分查找临界稀疏度
        
        while True:
            sparsity = (sparsity_l + sparsity_r) / 2
            x = torch.rand(size=[batch_size, self.in_features], device=device)
            sparse = (x > sparsity).to(x)
            sparsity_a = (sparse == 0).to(x).mean().item()  # sparse的真实稀疏度

            # 计算稀疏前反向所需时间
            t_list = []
            for _ in range(run_times * 2):
                fc_sparse.zero_grad()
                torch.cuda.synchronize()
                t_start = time.perf_counter()
                fc_sparse(sparse).sum().backward()
                torch.cuda.synchronize()
                t_list.append(time.perf_counter() - t_start)
            t_list = np.asarray(t_list)
            t_sparse = t_list[run_times:].sum()

            # 计算稠密前反向所需时间
            t_list = []
            for _ in range(run_times * 2):
                fc_dense.zero_grad()
                torch.cuda.synchronize()
                t_start = time.perf_counter()
                fc_dense(sparse).sum().backward()
                torch.cuda.synchronize()
                t_list.append(time.perf_counter() - t_start)
            t_list = np.asarray(t_list)
            t_dense = t_list[run_times:].sum()
            if verbose:
                print(f'sparsity_a={sparsity_a}, t_sparse={t_sparse}, t_dense={t_dense}')
            
            if t_sparse > t_dense:
                sparsity_l = sparsity_a
            elif t_sparse < t_dense:
                sparsity_r = sparsity_a
            else:
                break

            if sparsity_r - sparsity_l  < precision:
                break
            
        if t_sparse < t_dense:
            # 如果搜索达到精度范围后，稀疏乘法仍然比普通乘法慢，则永远不调用稀疏乘法
            # 所以只有t_sparse < t_dense才会记录入字典
            self.critical_sparsity[batch_size] = sparsity_a



                
                




                


