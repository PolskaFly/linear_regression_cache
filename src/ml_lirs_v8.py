import sys
import os
import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.naive_bayes import BernoulliNB
from sklearn.naive_bayes import MultinomialNB
from sklearn.naive_bayes import ComplementNB
from sklearn.naive_bayes import GaussianNB
from sklearn import linear_model

# Maybe change it from being based on non resident. Instead it is based on accesses. Everything above an access is in the boundary.
class Node:
    def __init__(self, b_num):
        self.block_number = b_num
        self.is_resident = False
        self.is_hir = True
        self.LIRS_prev = None
        self.LIRS_next = None
        self.HIR_prev = None
        self.HIR_next = None
        self.recency = False  # Rmax boundary
        self.recency0 = False  # LRU boundary
        self.refer_times = 0
        self.evicted_times = 0
        self.reuse_distance = 0
        self.position = [0, 0, 1]


class Trace:
    def __init__(self, tName):
        self.trace_path = '/Users/polskafly/PycharmProjects/ML_Cache/trace/' + tName
        self.parameter_path = '/Users/polskafly/PycharmProjects/ML_Cache/cache_size/' + tName
        self.trace = []
        self.memory_size = []
        self.vm_size = -1
        self.trace_dict = dict()

    def get_trace(self):
        # print ("get trace from ", self.trace_path)
        with open(self.trace_path, "r") as f:
            for line in f.readlines():
                if not line == "*\n" and not line.strip() == "":
                    block_number = int(line)
                    self.trace.append(block_number)
                    self.trace_dict[block_number] = Node(block_number)
        self.vm_size = max(self.trace)
        return self.trace, self.trace_dict, len(self.trace)

    def get_parameter(self):
        # print ("get trace from ", self.parameter_path)
        with open(self.parameter_path, "r") as f:
            for line in f.readlines():
                if not line == "*\n":
                    self.memory_size.append(int(line.strip()))
        return self.memory_size


class WriteToFile:
    def __init__(self, tName, fp):
        self.tName = tName
        __location__ = "/Users/polskafly/PycharmProjects/ML_Cache/result_set/" + tName
        self.FILE = open(__location__ + "/ml_lirs_v8_" + fp, "w+")

    def write_to_file(self, *args):
        data = ",".join(args)
        # Store the hit&miss ratio
        self.FILE.write(data + "\n")


class LIRS_Replace_Algorithm:
    def __init__(self, t_name, vm_size, trace_dict, mem_size, trace_size, model, start_use_model, mini_batch):
        self.trace_name = t_name
        # re-initialize trace_dict
        for k, v in trace_dict.items():
            trace_dict[k] = Node(k)

        self.hot_pred = 0
        self.cold_pred = 0
        self.model = model
        self.trace_size = trace_size
        self.page_table = trace_dict  # {block number : Node}
        self.MEMORY_SIZE = mem_size
        self.Free_Memory_Size = mem_size
        HIR_PERCENTAGE = 1.0
        MIN_HIR_MEMORY = 2
        self.HIR_SIZE = mem_size * (HIR_PERCENTAGE / 100)
        if self.HIR_SIZE < MIN_HIR_MEMORY:
            self.HIR_SIZE = MIN_HIR_MEMORY

        self.dynamic_init = False

        self.Stack_S_Head = None
        self.Sack_S_Tail = None
        self.Stack_Q_Head = None
        self.Stack_Q_Tail = None

        self.lir_size = 0
        self.Rmax = None
        self.Rmax0 = None
        self.Rmax0_lost = False

        self.page_fault = 0
        self.page_hit = 0

        self.inter_hit_ratio = []
        self.dynamic_ratio = []
        self.virtual_time = []

        self.last_ref_block = -1

        self.count_exampler = 0
        self.train = False

        self.predict_times = 0
        self.predict_H_L = 0
        self.predict_L_H = 0
        self.out_stack_hit = 0

        self.temp_hit = 0
        self.temp_fault = 0

        self.mini_batch_X = np.array([])
        self.mini_batch_X = np.array([])

        self.position_importance = {0: 1, 1: 2, 2: 3} #changed weight

        self.start_use_model = start_use_model
        # self.mini_batch = mini_batch
        # self.start_use_model = mem_size * 2
        #self.mini_batch = mem_size

    def remove_stack_Q(self, b_num):
        if (not self.page_table[b_num].HIR_next and not self.page_table[b_num].HIR_prev):
            self.Stack_Q_Tail, self.Stack_Q_Head = None, None
        elif (self.page_table[b_num].HIR_next and self.page_table[b_num].HIR_prev):
            self.page_table[b_num].HIR_prev.HIR_next = self.page_table[b_num].HIR_next
            self.page_table[b_num].HIR_next.HIR_prev = self.page_table[b_num].HIR_prev
            self.page_table[b_num].HIR_next, self.page_table[b_num].HIR_prev = None, None
        elif (not self.page_table[b_num].HIR_prev):
            self.Stack_Q_Head = self.page_table[b_num].HIR_next
            self.Stack_Q_Head.HIR_prev.HIR_next = None
            self.Stack_Q_Head.HIR_prev = None
        elif (not self.page_table[b_num].HIR_next):
            self.Stack_Q_Tail = self.page_table[b_num].HIR_prev
            self.Stack_Q_Tail.HIR_next.HIR_prev = None
            self.Stack_Q_Tail.HIR_next = None
        else:
            raise ("Stack Q remove error \n")
        return True

    def add_stack_Q(self, b_num):
        if (not self.Stack_Q_Head):
            self.Stack_Q_Head = self.Stack_Q_Tail = self.page_table[b_num]
        else:
            self.page_table[b_num].HIR_next = self.Stack_Q_Head
            self.Stack_Q_Head.HIR_prev = self.page_table[b_num]
            self.Stack_Q_Head = self.page_table[b_num]

    def remove_stack_S(self, b_num):
        if (not self.page_table[b_num].LIRS_prev and not self.page_table[b_num].LIRS_next):
            return False

        if (self.page_table[b_num] == self.Rmax):
            self.Rmax = self.page_table[b_num].LIRS_prev
            self.find_new_Rmax()

        if (self.page_table[b_num].LIRS_prev and self.page_table[b_num].LIRS_next):
            self.page_table[b_num].LIRS_prev.LIRS_next = self.page_table[b_num].LIRS_next
            self.page_table[b_num].LIRS_next.LIRS_prev = self.page_table[b_num].LIRS_prev
            self.page_table[b_num].LIRS_prev, self.page_table[b_num].LIRS_next = None, None
        elif (not self.page_table[b_num].LIRS_prev):
            self.Stack_S_Head = self.page_table[b_num].LIRS_next
            self.Stack_S_Head.LIRS_prev.LIRS_next = None
            self.Stack_S_Head.LIRS_prev = None
        elif (not self.page_table[b_num].LIRS_next):
            self.Stack_S_Tail = self.page_table[b_num].LIRS_prev
            self.Stack_S_Tail.LIRS_next.LIRS_prev = None
            self.Stack_S_Tail.LIRS_next = None
        else:
            raise ("Stack S remove error \n")
        return True

    def add_stack_S(self, b_num):
        if (not self.Stack_S_Head):
            self.Stack_S_Head = self.Stack_S_Tail = self.page_table[b_num]
            self.Rmax = self.page_table[b_num]
        else:
            self.page_table[b_num].LIRS_next = self.Stack_S_Head
            self.Stack_S_Head.LIRS_prev = self.page_table[b_num]
            self.Stack_S_Head = self.page_table[b_num]
        return True

    def find_new_Rmax(self):
        if (not self.Rmax):
            raise ("Warning Rmax0 \n")
        while self.Rmax.is_hir == True:
            self.Rmax.recency = False

            if self.Rmax == self.Rmax0:
                self.find_new_Rmax0()

            self.Rmax = self.Rmax.LIRS_prev

    #function to prune the dynamic stack normally
    def find_new_Rmax0(self):
        if not self.Rmax0:
            raise ("Warning Rmax0 \n")
        if not self.Rmax0.LIRS_prev:
            return
        self.Rmax0.recency0 = False
        ptr = self.Rmax0.LIRS_prev
        while ptr:
            if not ptr.is_resident:
                break
            if not ptr.LIRS_prev:
                break
            ptr.recency0 = False
            ptr = ptr.LIRS_prev
        ptr.recency0 = True
        self.Rmax0 = ptr

        return self.Rmax0

    #Function that when the Rmax0 is accessed, it searches downwards. Edge case.
    def look_down(self):
        if not self.Rmax0:
            raise ("Warning Rmax0 \n")
        ptr = self.Rmax0.LIRS_next
        while ptr:
            if not ptr.is_resident:
                break
            if ptr == self.Rmax:
                break
            ptr.recency0 = True
            ptr = ptr.LIRS_next
        ptr.recency0 = True
        self.Rmax0 = ptr

    def find_rmax0_resident(self, block):
        if not self.Rmax0:
            raise ("Warning Rmax0 \n")
        ptr = self.Rmax0
        while ptr:
            if ptr == block:
                ptr.recency0 = True
                if not ptr.LIRS_prev:
                    self.Rmax0 = ptr
                    break
                ptr = ptr.LIRS_prev
                ptr.recency0 = True
                self.Rmax0 = ptr
                break
            ptr.recency0 = False
            ptr = ptr.LIRS_prev

    def get_reuse_distance(self, ref_block):
        ptr = self.Stack_S_Head
        count = 0
        while ptr:
            count += 1
            if ptr.block_number == ref_block:
                return count
            ptr = ptr.LIRS_next
        raise ("get reuse distance error!")

    def resident_number(self):
        count = 0
        for b_num, node in self.page_table.items():
            if node.is_resident:
                count += 1
        print(self.MEMORY_SIZE, count)

    def block_range(self, x):
        return int(np.math.floor(x / 100.0)) * 100

    def generate_features(self, *feature):
        pass

    def print_information(self):
        print("======== Results ========")
        print("trace : ", self.trace_name)
        print("memory size : ", self.MEMORY_SIZE)
        print("trace_size : ", self.trace_size)
        print("Q size : ", self.HIR_SIZE)
        print("page hit : ", self.page_hit)
        print("page fault : ", self.page_fault)
        print("Hit ratio: ", self.page_hit / (self.page_fault + self.page_hit) * 100)
        print("Total: ", (self.page_fault + self.page_hit))
        print("Out stack hit : ", self.out_stack_hit)
        print("Predict Hot: ", self.hot_pred)
        print("Predict Cold: ", self.cold_pred)
        print("Predict Times =", self.predict_times, "H->L", self.predict_H_L, "L->H", self.predict_L_H)
        return self.MEMORY_SIZE, self.page_fault / (self.page_fault + self.page_hit) * 100, self.page_hit / (
                    self.page_fault + self.page_hit) * 100, self.inter_hit_ratio, self.dynamic_ratio, self.virtual_time

    def print_stack(self, v_time):
        ptr = self.Stack_S_Head
        while (ptr):
            print("R" if ptr == self.Rmax0 else "", end="")
            print(ptr.block_number, end="-")
            ptr = ptr.LIRS_next
        print()

    def inter_ratios(self, v_time):
        if v_time % 500 == 0 and v_time != 0:
            counter = 0
            total = 0
            h = (self.page_hit - self.temp_hit) / ((self.page_fault - self.temp_fault) +
                                                   (self.page_hit - self.temp_hit)) * 100
            self.inter_hit_ratio.append(float(h))
            self.temp_hit = self.page_hit
            self.temp_fault = self.page_fault

            ptr = self.Rmax
            while ptr:
                total += 1
                if ptr.recency0:
                    counter += 1
                ptr = ptr.LIRS_prev
            self.dynamic_ratio.append(float((counter / total) * 100))
            self.virtual_time.append(v_time)

    def debug_print(self):
        count = 0
        total = 0
        ptr = self.Rmax
        while ptr:
            total += 1
            if ptr.recency0:
                count += 1
            ptr = ptr.LIRS_prev
        print(total)
        print(count)
        print(count/total)
        print()

    def LIRS(self, v_time, ref_block):

        self.inter_ratios(v_time)

        if not self.page_table[ref_block].recency:
            self.out_stack_hit += 1

        if (ref_block == self.last_ref_block):
            self.page_hit += 1
            return

        self.last_ref_block = ref_block
        self.page_table[ref_block].refer_times += 1
        if not self.page_table[ref_block].is_resident:
            self.page_fault += 1

            if self.Free_Memory_Size == 0:
                self.Stack_Q_Tail.is_resident = False
                self.Stack_Q_Tail.evicted_times += 1

                if self.Stack_Q_Tail.recency and not self.dynamic_init: # Initialization of dynamic stack.
                    self.Rmax0 = self.Stack_Q_Tail
                    ptr = self.Rmax0
                    while ptr:
                        ptr.recency0 = True
                        ptr = ptr.LIRS_prev
                    self.dynamic_init = True

                if self.Stack_Q_Tail.recency0 and self.dynamic_init and (self.Stack_Q_Tail.evicted_times%2) == 0:
                    self.find_new_Rmax0()

                self.remove_stack_Q(self.Stack_Q_Tail.block_number)  # func(): remove block in the tail of stack Q
                self.Free_Memory_Size += 1
            elif self.Free_Memory_Size > self.HIR_SIZE:
                self.page_table[ref_block].is_hir = False
                self.lir_size += 1

            self.Free_Memory_Size -= 1
        elif (self.page_table[ref_block].is_hir):
            self.remove_stack_Q(ref_block)  # func():

        if self.page_table[ref_block].is_resident:
            self.page_hit += 1

        if self.page_table[ref_block].refer_times > 0:
            self.count_exampler += 1
            # p_feature = self.position_importance[self.page_table[ref_block].position]

            # self.model.partial_fit(np.array([[self.page_table[ref_block].reuse_distance, p_feature] + [1 if i == self.page_table[ref_block].position else 0 for i in range(3)]]), np.array([1 if self.page_table[ref_block].recency else -1], ), classes = np.array([1, -1]))
            if self.mini_batch_X.all():
                self.mini_batch_X = np.array(
                    [self.page_table[ref_block].position + [self.page_table[ref_block].refer_times-self.page_table[ref_block].evicted_times]])
                self.mini_batch_Y = np.array([1 if self.page_table[ref_block].recency else -1]) #changed from .recency
            else:
                # print(self.mini_batch_X)
                # self.mini_batch_X = np.r_[self.mini_batch_X, [[p_feature] + [1 if i == self.page_table[ref_block].position else 0 for i in range(3)]]]
                self.mini_batch_X = np.r_[
                    self.mini_batch_X, [self.page_table[ref_block].position + [self.page_table[ref_block].refer_times-self.page_table[ref_block].evicted_times]]]
                self.mini_batch_Y = np.r_[self.mini_batch_Y, [1 if self.page_table[ref_block].recency else -1]]
            if len(self.mini_batch_X) == self.start_use_model:
                self.model.partial_fit(self.mini_batch_X, self.mini_batch_Y, classes=np.array([1, -1]))
                self.mini_batch_X = np.array([])
                self.mini_batch_Y = np.array([])

            # type feature
            position = [0, 0, 0]
            if (self.page_table[ref_block].recency0):
                position[0] = 1
            if (self.page_table[ref_block].recency):
                position[1] = 1
            if (not self.page_table[ref_block].recency):
                position[2] = 1
            self.page_table[ref_block].position = position

        # when use the data to predict the model
        if self.count_exampler == self.start_use_model:
            self.train = True

        if self.Rmax0: #if there is an rmax0, then everytime a block is moved to the top of LIRS, it gets a recency0
            if self.Rmax0 == self.page_table[ref_block] and self.Rmax0 != self.Rmax:  # if accessed block is rmax0, then prune to a new non res.
                self.look_down()
            elif self.Rmax0 == self.Rmax:
                self.find_new_Rmax0()
            elif self.page_table[ref_block].recency0:
                self.find_rmax0_resident(self.page_table[ref_block])

        self.remove_stack_S(ref_block)
        self.add_stack_S(ref_block)

        self.page_table[ref_block].is_resident = True
        # start predict
        if self.train:
            feature = np.array([self.page_table[ref_block].position + [self.page_table[ref_block].refer_times-self.page_table[ref_block].evicted_times]])
            prediction = self.model.predict(feature.reshape(1, -1))
            self.predict_times += 1
            if (self.page_table[ref_block].is_hir):
                if (prediction == 1):
                    # H -> L
                    # self.lir_size += 1
                    self.predict_H_L += 1
                    self.page_table[ref_block].is_hir = False
                    self.add_stack_Q(self.Rmax.block_number)  # func():
                    self.Rmax.is_hir = True
                    self.Rmax.recency = False
                    self.find_new_Rmax()
                    self.hot_pred += 1
                elif (prediction == -1):
                    # H -> H
                    self.add_stack_Q(ref_block)  # func():
                    self.cold_pred += 1
            else:
                # if prev LIR
                if (prediction == -1 and self.lir_size > self.HIR_SIZE):
                    # L -> H
                    self.predict_L_H += 1
                    self.lir_size -= 1
                    # print (v_time, ref_block, self.lir_size, "L -> H")
                    self.add_stack_Q(ref_block)  # func():
                    if (ref_block == self.Rmax.block_number):
                        self.Rmax.is_hir = True
                        self.Rmax.recency = False
                        self.find_new_Rmax()
                    else:
                        self.page_table[ref_block].is_hir = True

                elif (prediction == 1):
                    # L -> L do nothing
                    pass
        else:
            # origin lirs
            if (self.page_table[ref_block].is_hir and self.page_table[ref_block].recency):
                self.page_table[ref_block].is_hir = False
                self.lir_size += 1

                self.add_stack_Q(self.Rmax.block_number)  # func():
                self.Rmax.is_hir = True
                self.lir_size -= 1
                self.Rmax.recency = False
                self.find_new_Rmax()
            elif (self.page_table[ref_block].is_hir):
                self.add_stack_Q(ref_block)  # func():

        self.page_table[ref_block].recency = True
        if self.Rmax0:
            self.page_table[ref_block].recency0 = True
        self.page_table[ref_block].refer_times += 1


def main(t_name, start_predict, mini_batch):
    # result file
    FILE = WriteToFile(t_name, t_name)
    # get trace
    trace_obj = Trace(t_name)
    # get the trace
    trace, trace_dict, trace_size = trace_obj.get_trace()
    memory_size = trace_obj.get_parameter()
    for memory in memory_size:
        RATIO_FILE = WriteToFile(t_name, str(memory) + "_" + t_name + "_ratios")
        # model = MultinomialNB()
        #model = GaussianNB()
        model = linear_model.BayesianRidge()
        lirs_replace = LIRS_Replace_Algorithm(t_name, trace_obj.vm_size, trace_dict, memory, trace_size, model,
                                              start_predict, mini_batch)
        for v_time, ref_block in enumerate(trace):
            lirs_replace.LIRS(v_time, ref_block)

        memory_size, miss_ratio, hit_ratio, inter_hit_ratio, dynamic_ratio, virtual_time = lirs_replace.print_information()
        FILE.write_to_file(str(memory_size), str(miss_ratio), str(hit_ratio))
        for i in range(len(inter_hit_ratio)):
            RATIO_FILE.write_to_file(str(virtual_time[i]), str(inter_hit_ratio[i]), str(dynamic_ratio[i]))


if __name__ == "__main__":
    if (len(sys.argv) != 4):
        raise ("usage: python3 XXX.py trace_name start_predict mini_batch")
    t_name = sys.argv[1]
    start_predict = int(sys.argv[2])
    mini_batch = int(sys.argv[3])
    main(t_name, start_predict, mini_batch)