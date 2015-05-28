__author__ = 'Thushan Ganegedara'


import numpy as np
import math
import os
from scipy import optimize
from scipy import misc
from numpy import linalg as LA
from PIL import Image
from theano import function, config, shared, sandbox
import theano.tensor as T

class SparseAutoencoder(object):

    #the value specified in the argument for each variable is the default value
    #__init__ is called when the constructor of an object is called (i.e. created an object)

    #by reducing number of hidden from 400 -> 75 and hidden2 200 -> 25 got an error reduction of 540+ -> 387 (for numbers dataset)
    def __init__(self, n_inputs, n_hidden, input=None, W1=None, W2=None, b1=None, b2=None):

        if input is None:
            self.input = T.dmatrix('input')
        else:
            self.input = input

        #define global variables for n_inputs and n_hidden
        self.n_hidden = n_hidden
        self.n_inputs = n_inputs
        self.n_outputs = n_inputs

        #generate random weights for W
        if W1 == None:
            val_range1 = [-math.sqrt(6.0/(n_inputs+n_hidden+1)), math.sqrt(6.0/(n_inputs+n_hidden+1))]
            W1 = val_range1[0] + np.random.random_sample((n_inputs,n_hidden))*2.0*val_range1[1]
            W1 = np.asarray(W1,dtype=config.floatX)
            self.W1 = shared(value=W1, name='W1', borrow=True)

        if W2 == None:
            val_range2 = [-math.sqrt(6.0/(self.n_outputs+n_hidden+1)), math.sqrt(6.0/(self.n_outputs+n_hidden+1))]
            W2 = val_range2[0] + np.random.random_sample((n_hidden,self.n_outputs))*2.0*val_range2[1]
            W2 = np.asarray(W2,dtype=config.floatX)
            self.W2 = shared(value=W2, name='W2', borrow=True)

        #by introducing *0.05 to b1 initialization got an error dropoff from 360 -> 280
        if b1 == None:
            b1 = -0.01 + np.random.random_sample((n_hidden,)) * 0.02
            self.b1 = shared(value=np.asarray(b1, dtype=config.floatX), name='b1', borrow=True)

        if b2 == None:
            b2 = -0.02 + np.random.random_sample((self.n_outputs,)) * 0.04
            self.b2 = shared(value=np.asarray(b2, dtype=config.floatX), name='b2', borrow=True)

        self.theta = [self.W1,self.b1,self.W2,self.b2]

    def forward_pass(self):
        a2 = T.nnet.sigmoid(T.dot(self.input,self.W1) + self.b1)

        a3 = T.nnet.sigmoid(T.dot(a2,self.W2) + self.b2)
        return a2, a3


    # cost calculate the cost you get given all the inputs feed forward through the network
    # at the moment I am using the squared error between the reconstructed and the input
    # theta is a vector formed by unrolling W1,b1,W2,b2 in to a single vector
    # Theta will be the input that the optimization method trying to optimize
    def get_cost_and_weight_update(self, l_rate, lam):

        a2,a3 = self.forward_pass()

        #L = - T.sum(self.input * T.log(a3) + (1 - self.input) * T.log(1 - a3), axis=1)
        #cost = T.mean(L)
        L = 0.5 * T.sum(T.sqr(a3-self.input), axis=1)
        cost = T.mean(L) + (lam/2)*0.0

        gparams = T.grad(cost, self.theta)

        #zip is used to iterate over two lists in parallel. This says, give the updated values for
        #param and gparam (param and param - l_rate*gparam respectively) while enumerating
        #params and gparams in parallel
        updates = [
            (param, param - l_rate*gparam)
            for param, gparam in zip(self.theta, gparams)
        ]

        return cost, updates

    def get_params(self):
        return [self.W1, self.b1]

    def get_hidden_act(self):
        return T.nnet.sigmoid(T.dot(self.input,self.W1) + self.b1)

#this calls the __init__ method automatically
#dA = SparseAutoEncoder()
#dA.load_data()
#dA.back_prop()
#dA.test_back_prop_with_diff_grad_checks()

#dA.save_hidden()
#dA.save_reconstructed()
