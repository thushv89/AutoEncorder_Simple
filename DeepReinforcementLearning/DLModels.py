__author__ = 'Thushan Ganegedara'

import functools
import itertools

import theano
import theano.tensor as T

import numpy as np

def identity(x):
    return x

def chained_output(layers, x):
    '''
    This method is applying the given transformation (lambda expression) recursively
    to a sequence starting with an initial value (i.e. x)
    :param layers: sequence to perform recursion
    :param x: Initial value to start recursion
    :return: the final value (output after input passing through multiple neural layers)
    '''
    return functools.reduce(lambda acc, layer: layer.output(acc), layers, x)

def iterations_shim(func, iterations):
    '''
    Repeated calls to the same function
    :param func: The function
    :param iterations: number of times to call the function
    :return:
    '''

    def function(i):
        for _ in range(iterations):
            func(i)
    return func


class Transformer(object):

    #__slots__ save memory by allocating memory only to the varibles defined in the list
    __slots__ = ['layers','_x','_y','_logger']

    def __init__(self,layers):
        self.layers = layers
        self._x = None
        self._y = None
        self._logger = None


    def make_func(self, x, y, batch_size, output, update, transformed_x = identity):
        '''
        returns a Theano function that takes x and y inputs and return the given output using given updates
        :param x: input feature vectors
        :param y: labels of inputs
        :param batch_size: batch size
        :param output: the output to calculate (symbolic)
        :param update: how to get to output from input
        :return: Theano function
        '''
        idx = T.scalar('idx')
        given = {self._x : transformed_x(x[idx * batch_size : (idx + 1) * batch_size]),
                 self._y : y[idx * batch_size : (idx + 1) * batch_size]}

        return theano.function(inputs=[idx],outputs=output, updates=update, givens=given, on_unused_input='warn')

    def process(self, x, y):
        '''
        Visit function with visitor pattern
        :param x:
        :param y:
        :return:
        '''
        pass

    def train_func(self, arc, learning_rate, x, y, batch_size, transformed_x=identity):
        '''
        Train the network with given params
        :param learning_rate: How fast it learns
        :param x: input feature vectors
        :param y: labels of inputs
        :param batch_size:
        :return: None
        '''
        pass

    def validate_func(self, arc, x, y, batch_size, transformed_x=identity):
        '''
        Validate the network with given parames
        :param x:
        :param y:
        :param batch_size:
        :return:
        '''
        pass

    def error_func(self, arc, x, y, batch_size, transformed_x = identity):
        '''
        Calculate error
        :param x:
        :param y:
        :param batch_size:
        :return:
        '''
        pass


class DeepAutoencoder(Transformer):
    ''' General Deep Autoencoder '''
    def __init__(self,layers, corruption_level, rng):
        super.__init__(layers)
        self._rng = rng
        self._corr_level = corruption_level

        self.theta = None
        self.cost = None
        # Need to find out what cost_vector is used for...
        self.cost_vector = None
        self.validation_error = None

    def process(self, x, y):
        self._x = x
        self._y = y

        # encoding input
        for layer in self.layers:
            W, b_prime = layer.W, layer.b_prime

            #if rng is specified corrupt the inputs
            if self._rng:
                x_tilde = self._rng.binomial(size=(x.shape[0], x.shape[1]), n=1,  p=(1 - self._corruption_level), dtype=theano.config.floatX) * x
                y = layer.output(x_tilde)
            else:
                y = layer.output(x)
                # z = T.nnet.sigmoid(T.dot(y, W.T) + b_prime) (This is required for regularization)

            x = y

        # decoding output and obtaining reconstruction
        for layer in reversed(self.layers):
            W, b_prime = layer.W, layer.b_prime
            x = T.nnet.sigmoid(T.dot(x,W.T) + b_prime)

        # costs
        # cost vector seems to hold the reconstruction error for each training case.
        # this is required for getting inputs with reconstruction error higher than average
        self.cost_vector = T.sum(T.nnet.binary_crossentropy(x, self._x),axis=1)
        self.theta = [ param for layer in self.layers for param in [layer.W, layer.b, layer.b_prime]]
        self.cost = T.mean(self.cost_vector)
        self.validation_error = None
        return None

    def train_func(self, _, learning_rate, x, y, batch_size, transformed_x=identity):
        updates = [(param, param - learning_rate*grad) for param, grad in zip(self.theta, T.grad(self.cost,wrt=self.theta))]
        return self.make_func(x=x,y=y,batch_size=batch_size,output=None, updates=updates, transformed_x=transformed_x)

    def indexed_train_func(self, arc, learning_rate, x, batch_size, transformed_x):

        nnlayer = self.layers[arc]
        # clone is used to substitute a computational subgraph
        transformed_cost = theano.clone(self.cost, replace={self._x : transformed_x(self._x)})

        # find out what happens in this updates list
        updates = [
            (nnlayer.W, T.inc_subtensor(nnlayer.W[:,nnlayer.idx], - learning_rate * T.grad(transformed_cost, nnlayer.W)[:,nnlayer.idx].T)),
            (nnlayer.b, T.inc_subtensor(nnlayer.b[nnlayer.idx], - learning_rate * T.grad(transformed_cost,nnlayer.b)[nnlayer.idx])),
            (nnlayer.b_prime, - learning_rate * T.grad(transformed_cost, nnlayer.b_prime))
        ]

        idx = T.iscalar('idx')
        givens = {self._x: x[idx * batch_size:(idx+1) * batch_size]}
        return theano.function([idx,nnlayer.idx], None, updates=updates, givens=givens)

    def validate_func(self, _, x, y, batch_size, transformed_x=identity):
        return self.make_func(x=x,y=y,batch_size=batch_size,output=self.validation_error, update=None, transformed_x=transformed_x)

    def get_hard_examples(self, _, x, y, batch_size, transformed_x=identity):
        '''
        Returns the set of training cases (above avg reconstruction error)
        :param _:
        :param x:
        :param y:
        :param batch_size:
        :return:
        '''
        # sort the values by cost and get the top half of it (above average error)
        indexes = T.argsort(self.cost_vector)[(self.cost_vector.shape[0] // 2):]
        return self.make_func(x=x, y=y, batch_size=batch_size, output=[self._x[indexes], self._y[indexes]], update=None, transformed_x=transformed_x)

class StackedAutoencoder(Transformer):
    ''' Stacks a set of autoencoders '''
    def __init__(self, layers, corruption_level, rng):
        super.__init__(layers)
        self._autoencoders = [DeepAutoencoder([layer], corruption_level, rng) for layer in layers]

    def process(self, x, y):
        self._x = x
        self._y = y

        for autoencoder in self._autoencoders:
            autoencoder.process(x,y)

    def train_func(self, arc, learning_rate, x, y, batch_size, transformed_x=identity):
        return self._autoencoders[arc].train_func(0, learning_rate,x,y,batch_size, lambda x: chained_output(self.layers[:arc],transformed_x(x)))

    def validate_func(self, arc, x, y, batch_size, transformed_x = identity):
        return self._autoencoders[arc].validate_func(0,x,y,batch_size,lambda x: chained_output(self.layers[:arc],transformed_x(x)))

class Softmax(Transformer):

    def __init__(self, layers, iterations):
        super.__init__(layers)

        self.theta = None
        self._errors = None
        self.cost_vector = None
        self.cost = None
        self.iterations = iterations

    def process(self, x, y):
        self._x = x
        self._y = y

        p_y_given_x = T.nnet.softmax(chained_output(self.layers, x))

        results = T.argmax(p_y_given_x, axis=1)

        self.theta = [param for layer in self.layers for param in [layer.W, layer.b]]
        self.errors = T.mean(T.neq(results,y))
        self.cost_vector = -T.log(p_y_given_x)[T.arrange(y.shape[0]), y]
        self.cost = T.mean(self.cost_vector)

        return None

    def train_func(self, arc, learning_rate, x, y, batch_size, transformed_x=identity, iterations=None):

        if iterations is None:
            iterations = self.iterations

        updates = [(param, param - learning_rate*grad) for param, grad in zip(self.theta, T.grad(self.cost,wrt=self.theta))]

        train = self.make_func(x,y,batch_size,None,updates,transformed_x)
        return iterations_shim(train, iterations)

    def validate_func(self, arc, x, y, batch_size, transformed_x=identity):
        return self.make_func(x,y,batch_size,self.cost,None,transformed_x)

    def error_func(self, arc, x, y, batch_size, transformed_x = identity):
        return self.make_func(x,y,batch_size,self._errors,None, transformed_x)

class Pool(object):
    ''' A ring buffer (Acts as a Queue) '''
    __slots__ = ['size', 'max_size', 'position', 'data', 'data_y', '_update']

    def __init__(self, row_size, max_size):
        self.size = 0
        self.max_size = max_size
        self.position = 0

        self.data = theano.shared(np.empty(max_size, row_size, dtype=theano.config.floatX), 'pool' )
        self.data_y = theano.shared(np.empty(max_size, dtype='int32'), 'pool_y')

        x = T.matrix('new_data')
        y = T.ivector('new_data_y')
        pos = T.iscalar('update_index')

        update = [(self.data, T.set_subtensor(self.data[pos:pos+x.shape[0]],x)),
            (self.data_y, T.set_subtensor(self.data_y[pos:pos+y.shape[0]],y))]

        self._update = theano.function([pos, x, y], updates=update)

    def add(self, x, y, rows=None):

        if not rows:
            rows = x.shape[0]

        if rows > self.max_size:
            x = x[rows - self.max_size]
            y = y[rows - self.max_size]

        if rows+ self.position > self.max_size:
            available_size = self.max_size - self.position
            self._ring_add(x[:available_size], y[:available_size])
            x = x[available_size:]
            y = y[available_size:]

        self._ring_add(x,y)

    def clear(self):
        self.size = 0
        self.position = 0

    def _ring_add(self, x, y):
        self._update(self.position, x, y)
        self.size = min(self.size + x.shape[0], self.max_size)
        self.position = (self.position + x.shape[0]) % self.max_size

class MergeIncrementingAutoencoder(Transformer):

    __slots__ = ['_autoencoder', '_layered_autoencoders', '_combined_objective', '_softmax', 'lam', '_updates', '_givens', 'rng', 'iterations']

    def __init__(self, layers, corruption_level, rng, lam, iterations):
        super.__init__(layers)

        self._autoencoder = DeepAutoencoder(layers[:-1], corruption_level, rng)
        self._layered_autoencoders = [DeepAutoencoder([self.layers[i]], corruption_level, rng)
                                       for i, layer in enumerate(self.layers[:-1])]
        self._softmax = Softmax(layers)
        self._combined_objective = CombinedObjective(layers, corruption_level, rng, lam, iterations)
        self.lam = lam
        self.iterations = iterations
        self.rng = np.random.RandomState(0)

    def process(self, x, y):
        self._x = x
        self._y = y
        self._autoencoder.process(x,y)
        self._softmax.process(x,y)
        self._combined_objective.process(x,y)
        for ae in self._layered_autoencoders:
            ae.process(x,y)

    def merge_inc_func(self, learning_rate, batch_size, x, y):

        m = T.matrix('m')
        # map operation applies a certain function to a sequence. This is the upper part of cosine dist eqn
        m_dists, _ = theano.map(lambda v: T.sqrt(T.dot(v, v.T)), m)
        # dimshuffle(0,'x') is converting N -> Nx1
        m_cosine = (T.dot(m, m.T)/m_dists) / m_dists.dimshuffle(0,'x')

        # T.tri gives a matrix with 1 below diagonal (including diag) and zero elsewhere
        # flatten() gives a view of tensor nDim-1 as the original and last dim having all the data in original
        # finfo gives the maximum value of floats
        m_ranks = T.argsort((m_cosine - T.tri(m.shape[0]) * np.finfo(theano.config.floatX).max).flatten())[(m.shape[0] * (m.shape[0]+1)) // 2:]

        score_merges = theano.function([m], m_ranks)

        # greedy layer-wise training
        layer_greedy = [ae.indexed_train_func(0, learning_rate, x, batch_size, lambda  x, j=i: chained_output(self.layers[:j], x)) for i, ae in enumerate(self._layered_autoencoders)]
        finetune = self._autoencoder.train_func(0, learning_rate, x, y, batch_size)
        combined_objective_tune = self._combined_objective.train_func(0, learning_rate, x, y, batch_size)

        # set up cost function
        mi_cost = self._softmax.cost + self.lam * self._autoencoder.cost
        mi_updates = []

        # calculating merge_inc updates
        # increment a subtensor by a certain value
        for i, nnlayer in enumerate(self._autoencoder.layers):
            if i == 0:
                mi_updates += [(nnlayer.W, T.inc_subtensor(nnlayer.W, T.inc_subtensor(nnlayer.W[:,nnlayer.idx], - learning_rate * T.grad(mi_cost, nnlayer.W)[:,nnlayer.idx].T)))]
                mi_updates += [(nnlayer.b, T.inc_subtensor(nnlayer.b[nnlayer.idx], - learning_rate*T.grad(mi_cost,nnlayer.b)[nnlayer.idx]))]
            else:
                mi_updates += [(nnlayer.W, nnlayer.W - learning_rate * T.grad(mi_cost, nnlayer.W))]
                mi_updates += [(nnlayer.b, nnlayer.b - learning_rate * T.grad(mi_cost,nnlayer.b))]

            mi_updates += [(nnlayer.b_prime, -learning_rate * T.grad(mi_cost,nnlayer.b_prime))]

        softmax_theta = [self.layers[-1].W, self.layers[-1].b]

        mi_updates += [(param, param - learning_rate * grad) for param,grad in zip(softmax_theta, T.grad(mi_cost,softmax_theta))]

        idx = T.iscalar('idx')

        given = {
            self._x : x[idx*batch_size : (idx+1) * batch_size],
            self._y : y[idx*batch_size : (idx+1) * batch_size]
        }

        mi_train = theano.function([idx, self.layers[0].idx], None, updates=mi_updates, givens=given)

        def merge_model(pool_indexes, merge_percentage, inc_percentage):
            '''
            Merge/Increment the batch using given pool of data
            :param pool_indexes:
            :param merge_percentage:
            :param inc_percentage:
            :return:
            '''

            prev_map = {}
            prev_dimensions = self.layers[0].initial_size[0]

            used = set()
            empty_slots = []

            # first layer
            layer_weights = self.layers[0].W.get_value().T.copy()
            layer_bias = self.layers[0].b.get_value().copy()

            # initialization of weights
            init = 4 * np.sqrt(6.0 / (sum(layer_weights.shape())))

            # number of nodes to merge or increment
            merge_count = int(merge_percentage * layer_weights.shape[0])
            inc_count = int(inc_percentage * layer_weights.shape[0])

            # if there's nothing to merge or increment
            if merge_count == 0 and inc_count == 0:
                return

            # get the highest ranked node indexes
            for index in score_merges(layer_weights):
                if len(empty_slots) == merge_count:
                    break

                # x and y coordinates created out of index (assume these are the two nodes
                # to merge)
                x_i, y_i = index % layer_weights.shape[0], index // layer_weights.shape[0]

                # if x_i and y_i are not in "used"`  list
                if x_i not in used and y_i not in used:
                    # update weights and bias with avg
                    layer_weights[x_i] = (layer_weights[x_i] + layer_weights[y_i])/2
                    layer_bias[x_i] = (layer_bias[x_i] + layer_bias[y_i])/2

                    #add it to the used list
                    used.update([x_i,y_i])
                    empty_slots.append(y_i)

            #get the new size of layer
            new_size = layer_weights.shape[0] + inc_count - len(empty_slots)
            current_size = layer_weights.shape[0]

            # if new size is less than current...
            if new_size < current_size:
                non_empty_slots = sorted(list(set(range(0,current_size)) - set(empty_slots)), reverse=True)[:len(empty_slots)]
                prev_map = dict(zip(empty_slots, non_empty_slots))

                for dest, src in prev_map.items():
                    layer_weights[dest] = layer_weights[src]
                    layer_weights[src] = np.asarray(self.rng.uniform(low=init, high=init, size=layer_weights.shape[1]), dtype=theano.config.floatX)

                empty_slots = []

            else:
                prev_map = {}

            new_layer_weights = np.zeros((new_size,prev_dimensions), dtype = theano.config.floatX)
            new_layer_weights[:layer_weights.shape[0], :layer_weights.shape[1]] = layer_weights[:new_layer_weights.shape[0], :new_layer_weights.shape[1]]

            empty_slots = [slot for slot in empty_slots if slot < new_size] + list(range(layer_weights.shape[0],new_size))
            new_layer_weights[empty_slots] = np.asarray(self.rng.uniform(low=-init, high=init, size=(len(empty_slots), prev_dimensions)), dtype=theano.config.floatX)

            layer_bias.resize(new_size)

            layer_bias_prime = self.layers[0].b_prime.get_value().copy()
            layer_bias_prime.resize(prev_dimensions)

            prev_dimensions = new_layer_weights.shape[0]

            self.layers[0].W.set_value(new_layer_weights.T)
            self.layers[0].b.set_value(layer_bias)
            self.layers[0].b_prime.set_value(layer_bias_prime)

            if empty_slots:

                for _ in range(self.iterations):
                    for i in pool_indexes:
                        layer_greedy[0](i, empty_slots)

            last_layer_weights = self.layers[1].W.get_value().copy()

            for dest, src in prev_map.items():
                last_layer_weights[dest] = last_layer_weights[src]
                last_layer_weights[src] = np.zeros(last_layer_weights.shape[1])

            last_layer_weights.resize((prev_dimensions, self.layers[1].initial_size[1]))
            last_layer_prime = self.layers[1].b_prime.get_value().copy()
            last_layer_prime.resize(prev_dimensions)

            self.layers[1].W.set_value(last_layer_weights)
            self.layers[1].b_prime.set_value(last_layer_prime)

            for _ in range(self.iterations):
                for i in pool_indexes:
                    finetune(i)

            if empty_slots:
                for _ in range(self.iterations):
                    for i in pool_indexes:
                        mi_train(i, empty_slots)
            else:
                for i in pool_indexes:
                    combined_objective_tune(i)

        return merge_model


class CombinedObjective(Transformer):

    def __init__(self, layers, corruption_level, rng, lam, iterations):
        super.__init__(layers)

        self._autoencoder = DeepAutoencoder(layers[:-1], corruption_level, rng)
        self._softmax = Softmax(layers)
        self.lam = lam
        self.iterations = iterations

    def process(self, x, yy):
        self._x = x
        self._y = yy

        self._autoencoder.process(x,yy)
        self._softmax.process(x,yy)

    def train_func(self, arc, learning_rate, x, y, batch_size, transformed_x=identity, iterations = None):

        if iterations is None:
            iterations = self.iterations

        combined_cost = self._softmax.cost + self.lam * self._autoencoder.cost

        theta = []
        for layer in self.layers[:-1]:
            theta += [layer.W, layer.b, layer.b_prime]
        theta += [self.layers[-1].W, self.layers[-1].b] #softmax layer

        update = [(param, param - learning_rate * grad) for param, grad in zip(theta, T.grad(combined_cost,wrt=theta))]
        func = self.make_func(x, y, batch_size, None, update, transformed_x)
        return iterations_shim(func, iterations)

    def validate_func(self, arc, x, y, batch_size, transformed_x=identity):
        return self._softmax.validate_func(arc, x, y, batch_size, transformed_x)

    def error_func(self, arc, x, y, batch_size, transformed_x = identity):
        return self._softmax.error_func(arc, x, y, batch_size, transformed_x)


class DeepReinforcementLearningModel(Transformer):

    def __init__(self, layers, corruption_level, rng, iterations, lam, mi_batch_size, pool_size, controller):

        super.__init__(layers)

        self._mi_batch_size = mi_batch_size
        self._controller = controller
        self._autoencoder = DeepAutoencoder(layers[:-1], corruption_level, rng)
        self._softmax = CombinedObjective(layers, corruption_level, rng, lam, iterations)
        self._merge_increment = MergeIncrementingAutoencoder(layers, corruption_level, rng, lam, iterations)

        self._pool = Pool(layers[0].initial_size[0], pool_size)
        self._hard_pool = Pool(layers[0].initial_size[0], pool_size)

    def process(self, x, y):
        self._autoencoder.process(x, y)
        self._softmax.process(x, y)
        self._merge_increment.process(x, y)

    def train_func(self, arc, learning_rate, x, y, batch_size, apply_x=identity):
        batch_pool = Pool(self.layers[0].initial_size[0], batch_size)

        train_func = self._softmax.train_func(arc, learning_rate, x, y, batch_size, apply_x)
        reconstruction_func = self._autoencoder.validate_func(arc, x, y, batch_size, apply_x)
        error_func = self.error_func(arc, x, y, batch_size, apply_x)

        merge_inc_func_batch = self._merge_increment.merge_inc_func(learning_rate, self._mi_batch_size, x, y)
        merge_inc_func_pool = self._merge_increment.merge_inc_func(learning_rate, self._mi_batch_size, self._pool.data, self._pool.data_y)
        merge_inc_func_hard_pool = self._merge_increment.merge_inc_func(learning_rate, self._mi_batch_size, self._hard_pool.data, self._hard_pool.data_y)

        hard_examples_func = self._autoencoder.get_hard_examples(arc, x, y, batch_size, apply_x)

        train_func_pool = self._softmax.train_func(arc, learning_rate, self._pool.data, self._pool.data_y, batch_size, apply_x)
        train_func_hard_pool = self._softmax.train_func(arc, learning_rate, self._hard_pool.data, self._hard_pool.data_y, batch_size, apply_x)

        neuron_balance = 1

        def train_pool(pool, pool_func, amount):

            for i in pool.as_size(int(pool.size * amount), batch_size):
                pool_func(i)

        def moving_average(log, n):

            weights = np.exp(np.linspace(-1, 0, n))
            weights /= sum(weights)
            return np.convolve(log, weights)[n-1:-n+1]

        def pool_relevant(pool):

            def magnitude(x):
                '''  returns sqrt(sum(v(i)^2)) '''
                return sum((v **2 for v in x.values() )) ** 0.5

            def compare(x,y):
                '''  Calculate Cosine distance between x and y '''
                top = 0

                for k in set(x) | set(y):
                    xval, yval = x[k] if k in x else 0, y[k] if k in y else 0
                    top += xval * yval

                return top / magnitude(x) * magnitude(y)

            # score over batches for this pool
            batches_covered = pool.size // batch_size
            batch_scores = [(i % batches_covered, compare(current, self.context['distribution'][i])) for i in range(-1,-1 - batches_covered)]
            mean = np.mean([ v[1] for v in batch_scores ])
