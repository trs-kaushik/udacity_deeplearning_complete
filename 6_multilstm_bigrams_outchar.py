__author__ = 'Thushan Ganegedara'

import os
import numpy as np
import random
import string
import tensorflow as tf
import zipfile
from six.moves import range
from six.moves.urllib.request import urlretrieve
import math
import collections
from math import ceil
url = 'http://mattmahoney.net/dc/'

def maybe_download(filename, expected_bytes):
  """Download a file if not present, and make sure it's the right size."""
  if not os.path.exists(filename):
    filename, _ = urlretrieve(url + filename, filename)
  statinfo = os.stat(filename)
  if statinfo.st_size == expected_bytes:
    print('Found and verified %s' % filename)
  else:
    print(statinfo.st_size)
    raise Exception(
      'Failed to verify ' + filename + '. Can you get to it with a browser?')
  return filename

filename = maybe_download('text8.zip', 31344016)

def read_data(filename):
  f = zipfile.ZipFile(filename)
  for name in f.namelist():
    return tf.compat.as_str(f.read(name))
  f.close()

text = read_data(filename)
print('Data size %d' % len(text))


def read_data_as_bigrams(filename,overlap):
    """Extract the first file enclosed in a zip file as a list of words"""
    with zipfile.ZipFile(filename) as f:
        data = tf.compat.as_str(f.read(f.namelist()[0]))

    list_data = list()
    for c_i,char in enumerate(data):
        if not overlap and c_i%2==1:
            continue
        if c_i == len(data)-1:
            continue
        list_data.append(char+data[c_i+1])
    return list_data

skip_bigrams = read_data_as_bigrams(filename,False)
overlap_bigrams = read_data_as_bigrams(filename,True)

print('Data size %d' % len(skip_bigrams))
print('First %d bigrams: %s' %(10,skip_bigrams[:10]))
assert len(skip_bigrams[0])==2

def build_dataset(bigrams):
    # UNK token is used to denote words that are not in the dictionary
    count = [['UNK', -1]]
    count.extend(collections.Counter(bigrams).most_common())

    print('Bigram counts...')
    print_i = 0
    for ele in count:
        if print_i>5:
            break
        print('\tkey=',ele[0],',value=',ele[1])
        print_i += 1

    dictionary = dict()
    # set word count for all the words to the current number of keys in the dictionary
    # in other words values act as indices for each word
    # first word is 'UNK' representing unknown words we encounter
    for bigram, _ in count:
        dictionary[bigram] = len(dictionary)
    # this contains the words replaced by assigned indices
    data = list()
    unk_count = 0
    for bigram in bigrams:
        if (bigram[0] in string.ascii_lowercase or bigram[0]==' ') and \
                (bigram[1] in string.ascii_lowercase or bigram[1]==' '):
            index = dictionary[bigram]
        else:
            index = 0  # dictionary['UNK']
            unk_count = unk_count + 1
        data.append(index)
    count[0][1] = unk_count
    reverse_dictionary = dict(zip(dictionary.values(), dictionary.keys()))
    return data, count, dictionary, reverse_dictionary

# dictionary => 'ab' => 1234
# reverse_dictionary  => 1234 => 'ab'
data, count, dictionary, reverse_dictionary = build_dataset(skip_bigrams)

data_index = 0

def generate_batch(batch_size, skip_window):
    # skip window is the amount of words we're looking at from each side of a given word
    # creates a single batch
    global data_index

    span = 2 * skip_window + 1 # [ skip_window target skip_window ]
    assert span%2==1

    batch = np.ndarray(shape=(batch_size,span-1), dtype=np.int32)
    labels = np.ndarray(shape=(batch_size, 1), dtype=np.int32)
    # e.g if skip_window = 2 then span = 5
    # span is the length of the whole frame we are considering for a single word (left + word + right)
    # skip_window is the length of one side

    # queue which add and pop at the end
    buffer = collections.deque(maxlen=span)

    #get words starting from index 0 to span
    for _ in range(span):
        buffer.append(data[data_index])
        data_index = (data_index + 1) % len(data)

    # num_skips => # of times we select a random word within the span?
    # batch_size (8) and num_skips (2) (4 times)
    # batch_size (8) and num_skips (1) (8 times)
    for i in range(batch_size):
        target = skip_window  # target label at the center of the buffer
        target_to_avoid = [ skip_window ] # we only need to know the words around a given word, not the word itself

        # do this num_skips (2 times)
        # do this (1 time)

        # add selected target to avoid_list for next time
        col_idx = 0
        for j in range(span):
            if j==span//2:
                continue
            # e.g. i=0, j=0 => 0; i=0,j=1 => 1; i=1,j=0 => 2
            batch[i,col_idx] = buffer[j] # [skip_window] => middle element
            col_idx += 1
        labels[i, 0] = buffer[target]

        buffer.append(data[data_index])
        data_index = (data_index + 1) % len(data)

    assert batch.shape[0]==batch_size and batch.shape[1]== span-1
    return batch, labels

def char2id(char):
  if char in string.ascii_lowercase:
    return ord(char) - first_letter + 1
  elif char == ' ':
    return 0
  else:
    print('Unexpected character: %s' % char.encode('utf-8'))
    return 0

def id2char(dictid):
  if dictid > 0:
    return chr(dictid + first_letter - 1)
  else:
    return ' '


valid_size = 500
valid_text = overlap_bigrams[:valid_size]
train_text = overlap_bigrams[valid_size:]
train_size = len(train_text)

print(train_size, train_text[:64])
print(valid_size, valid_text[:64])

bigram_vocabulary_size = len(count)
char_vocabulary_size = 27
print("Vocabulary Size: %d"%bigram_vocabulary_size)
first_letter = ord(string.ascii_lowercase[0])


batch_size=64
num_unrollings=10 # new number of batches to add to training data

class BatchGeneratorWithCharLabels(object):
  def __init__(self, text_as_bigrams, batch_size, num_unrollings):
    self._text = text_as_bigrams

    self._text_size = len(self._text)
    self._batch_size = batch_size
    self._num_unrollings = num_unrollings
    segment = self._text_size // batch_size
    self._cursor = [ offset * segment for offset in range(batch_size)]
    self._last_batch = self._next_batch()

  def _next_batch(self):
    """Generate a single batch from the current cursor position in the data."""
    batch = np.zeros(shape=(self._batch_size,), dtype=np.int32)
    batch_labels = np.zeros(shape=(self._batch_size,), dtype=np.int32)

    for b in range(self._batch_size):
        key = self._text[self._cursor[b]]
        batch[b] = dictionary[key]
        batch_labels[b] = char2id(self._text[self._cursor[b]+1][1])
        self._cursor[b] = (self._cursor[b] + 1) % self._text_size
    return batch,batch_labels

  def next(self):
    """Generate the next array of batches from the data. The array consists of
    the last batch of the previous array, followed by num_unrollings new ones.
    """
    batches = [self._last_batch]
    for step in range(self._num_unrollings-1):
      batches.append(self._next_batch())
    self._last_batch = batches[-1]
    return batches

class BatchGeneratorWithCharLabelsWithSequence(object):
  def __init__(self, text_as_bigrams, batch_size, num_unrollings, seq_size):
    self._text = text_as_bigrams

    self._text_size = len(self._text)
    self._batch_size = batch_size
    self._num_unrollings = num_unrollings
    self.seq_size = seq_size
    segment = self._text_size // batch_size
    self._cursor = [ offset * segment for offset in range(batch_size)]
    self._last_batch = self._next_batch()

  def _next_batch(self):
    """Generate a single batch from the current cursor position in the data."""
    batch = np.zeros(shape=(self._batch_size,self.seq_size), dtype=np.int32)
    batch_labels = np.zeros(shape=(self._batch_size,), dtype=np.int32)

    for b in range(self._batch_size):
        for seq_id in range(self.seq_size):
            key = self._text[self._cursor[b]]
            batch[b,seq_id] = dictionary[key]
            self._cursor[b] = (self._cursor[b] + 1) % self._text_size
        batch_labels[b] = char2id(self._text[self._cursor[b]][0])
    return batch,batch_labels

  def next(self):
    """Generate the next array of batches from the data. The array consists of
    the last batch of the previous array, followed by num_unrollings new ones.
    """
    batches = [self._last_batch]
    for step in range(self._num_unrollings-1):
      batches.append(self._next_batch())
    self._last_batch = batches[-1]
    return batches

def characters(labels):
  """Turn a 1-hot encoding or a probability distribution over the possible
  characters back into its (most likely) character representation."""
  # need embedding look up
  return [reverse_dictionary[c] for c in labels[:]]

def batches2string(batches):
    """Convert a sequence of batches back into their (most likely) string
    representation."""
    s = [''] * batches[0].shape[0]
    for b in batches:
        s = [''.join(x) for x in zip(s, characters(b))]
    return s

def batches2string_with_tuples(batches):
    """Convert a sequence of batches back into their (most likely) string
    representation."""
    s_in = []
    s_out = []
    s_comb = []
    for (b,l) in batches:
        s_in.append(characters(b))
        s_out.append([id2char(o) for o in list(l.flatten())])
    for b_i,b_o in zip(s_in,s_out):
        tmp_s = []
        for b_i_j,b_o_j in zip(b_i,b_o):
            tmp_s.append(b_i_j+b_o_j)
        s_comb.append(tmp_s)
    return s_in,s_out,s_comb


train_batches = BatchGeneratorWithCharLabels(train_text, batch_size, num_unrollings)
valid_batches = BatchGeneratorWithCharLabels(valid_text, 1, 1)
input_strings,label_strings,comb_strings = batches2string_with_tuples(train_batches.next())
valid_input_strings,valid_label_strings,valid_comb_strings = batches2string_with_tuples(valid_batches.next())
print('Batch Inputs')
print(input_strings[:1])
print()
print(label_strings[:1])
print()
print(comb_strings[:1])


def logprob(predictions, labels):
  """Log-probability of the true labels in a predicted batch."""
  # Predictions is a list with exact same number of batches as the input batch list
  # and each batch is ndarray (batch_size x emb_size)
  predictions[predictions < 1e-10] = 1e-10
  return np.sum(np.multiply(labels, -np.log(predictions))) / labels.shape[0]

def prob(predictions, labels):
  """Log-probability of the true labels in a predicted batch."""
  # Predictions is a list with exact same number of batches as the input batch list
  # and each batch is ndarray (batch_size x emb_size)
  predictions[predictions < 1e-10] = 1e-10
  return np.sum(np.multiply(labels, predictions)) / labels.shape[0]

def sample_distribution(distribution):
  """Sample one element from a distribution assumed to be an array of normalized
  probabilities.
  """
  r = random.uniform(0, 1)
  s = 0
  for i in range(len(distribution)):
    s += distribution[i]
    if s >= r:
      return i
  return len(distribution) - 1

def sample(prediction):
  """ Turn a (column) prediction into 1-hot encoded samples. """
  p = np.zeros(shape=[1, embedding_size], dtype=np.float)
  # prediction[0] is the 1st row of prediction
  p[0, sample_distribution(prediction[0])] = 1.0
  return p

def random_distribution():
  """Generate a random column of probabilities for embeddings."""
  b = np.random.uniform(0.0, 1.0, size=[1, embedding_size])
  return b/np.sum(b, 1)[:,None]


num_nodes = [128,64]
skip_window = 2
embedding_size = 64
num_sampled = 64
use_dropout = False
dropout_rate = 0.25
beam_search = True
beam_distance = 2

assert num_sampled<=bigram_vocabulary_size

graph = tf.Graph()
with graph.as_default():


    # Input data.
    emb_train_dataset = tf.placeholder(tf.int32, shape=[batch_size,2*skip_window])
    emb_train_labels = tf.placeholder(tf.int32, shape=[batch_size, 1])
    #emb_valid_dataset = tf.constant(valid_examples, dtype=tf.int32)

    # Variables.
    # embedding, vector for each word in the vocabulary
    embeddings = tf.Variable(tf.random_uniform([bigram_vocabulary_size, embedding_size], -1.0, 1.0))
    emb_W = tf.Variable(tf.truncated_normal([bigram_vocabulary_size, embedding_size],
                     stddev=1.0 / math.sqrt(embedding_size)))
    emb_b = tf.Variable(tf.zeros([bigram_vocabulary_size]))

    embeds = None
    for i in range(2*skip_window):
        embedding_i = tf.nn.embedding_lookup(embeddings, emb_train_dataset[:,i])
        print('embedding %d shape: %s'%(i,embedding_i.get_shape().as_list()))
        emb_x,emb_y = embedding_i.get_shape().as_list()
        if embeds is None:
            embeds = tf.reshape(embedding_i,[emb_x,emb_y,1])
        else:
            embeds = tf.concat(2,[embeds,tf.reshape(embedding_i,[emb_x,emb_y,1])])

    assert embeds.get_shape().as_list()[2]==2*skip_window
    print("Concat embedding size: %s"%embeds.get_shape().as_list())
    avg_embed =  tf.reduce_mean(embeds,2,keep_dims=False)
    print("Avg embedding size: %s"%avg_embed.get_shape().as_list())

    # Compute the softmax loss, using a sample of the negative labels each time.
    # inputs are embeddings of the train words
    # with this loss we optimize weights, biases, embeddings

    emb_loss = tf.reduce_mean(tf.nn.sampled_softmax_loss(emb_W, emb_b, avg_embed,
                           emb_train_labels, num_sampled, bigram_vocabulary_size))
    emb_optimizer = tf.train.AdagradOptimizer(1.2).minimize(emb_loss)

    emb_norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
    emb_normalized_embeddings = embeddings / emb_norm

    #norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
    #normalized_embeddings = embeddings / norm
    #valid_embeddings = tf.nn.embedding_lookup(normalized_embeddings, valid_dataset)
    #similarity = tf.matmul(valid_embeddings, tf.transpose(normalized_embeddings))

    # Parameters:
    # x=>input, m=>model(output) state, b=>bias
    # Input gate: input, previous output (state), and bias.
    ix1 = tf.Variable(tf.truncated_normal([embedding_size, num_nodes[0]], -0.1, 0.1))
    im1 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[0]], -0.1, 0.1))
    ib1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    # Forget gate: input, previous output (state), and bias.
    fx1 = tf.Variable(tf.truncated_normal([embedding_size, num_nodes[0]], -0.1, 0.1))
    fm1 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[0]], -0.1, 0.1))
    fb1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    # Memory cell: input, state and bias.
    cx1 = tf.Variable(tf.truncated_normal([embedding_size, num_nodes[0]], -0.1, 0.1))
    cm1 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[0]], -0.1, 0.1))
    cb1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    # Output gate: input, previous output, and bias.
    ox1 = tf.Variable(tf.truncated_normal([embedding_size, num_nodes[0]], -0.1, 0.1))
    om1 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[0]], -0.1, 0.1))
    ob1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    # Variables saving state across unrollings.
    saved_output_1 = tf.Variable(tf.zeros([batch_size, num_nodes[0]]), trainable=False)
    saved_state_1 = tf.Variable(tf.zeros([batch_size, num_nodes[0]]), trainable=False)

    ix2 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[1]], -0.1, 0.1))
    im2 = tf.Variable(tf.truncated_normal([num_nodes[1], num_nodes[1]], -0.1, 0.1))
    ib2 = tf.Variable(tf.zeros([1, num_nodes[1]]))
    # Forget gate: input, previous output, and bias.
    fx2 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[1]], -0.1, 0.1))
    fm2 = tf.Variable(tf.truncated_normal([num_nodes[1], num_nodes[1]], -0.1, 0.1))
    fb2 = tf.Variable(tf.zeros([1, num_nodes[1]]))
    # Memory cell: input, state and bias.
    cx2 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[1]], -0.1, 0.1))
    cm2 = tf.Variable(tf.truncated_normal([num_nodes[1], num_nodes[1]], -0.1, 0.1))
    cb2 = tf.Variable(tf.zeros([1, num_nodes[1]]))
    # Output gate: input, previous output, and bias.
    ox2 = tf.Variable(tf.truncated_normal([num_nodes[0], num_nodes[1]], -0.1, 0.1))
    om2 = tf.Variable(tf.truncated_normal([num_nodes[1], num_nodes[1]], -0.1, 0.1))
    ob2 = tf.Variable(tf.zeros([1, num_nodes[1]]))

    # Variables saving state across unrollings.
    saved_output_2 = tf.Variable(tf.zeros([batch_size, num_nodes[1]]), trainable=False)
    saved_state_2 = tf.Variable(tf.zeros([batch_size, num_nodes[1]]), trainable=False)

    # Classifier weights and biases.
    w = tf.Variable(tf.truncated_normal([num_nodes[1], char_vocabulary_size], -0.1, 0.1))
    b = tf.Variable(tf.zeros([char_vocabulary_size]))


    def lstm_cell_1(i,o,state):
        if use_dropout:
            i = tf.nn.dropout(i,keep_prob=1.0 - dropout_rate,seed=tf.set_random_seed(12345))
        ifco_x1 = tf.concat(1,[ix1,fx1,cx1,ox1])
        ifco_o1 = tf.concat(1,[im1,fm1,cm1,om1])
        ifco_bias1 = tf.concat(1,[ib1,fb1,cb1,ob1])
        ifco_wx_plus_b_1 = tf.matmul(i,ifco_x1) + tf.matmul(o,ifco_o1) + ifco_bias1
        input_gate_1 = tf.sigmoid(tf.slice(ifco_wx_plus_b_1,[0,0],[-1,num_nodes[0]]))
        forget_gate_1 = tf.sigmoid(tf.slice(ifco_wx_plus_b_1,[0,num_nodes[0]],[-1,num_nodes[0]]))
        update = tf.slice(ifco_wx_plus_b_1,[0,2*num_nodes[0]],[-1,num_nodes[0]])
        state = forget_gate_1 * state + input_gate_1 * tf.tanh(update)
        output_gate = tf.sigmoid(tf.slice(ifco_wx_plus_b_1,[0,3*num_nodes[0]],[-1,num_nodes[0]]))
        return output_gate * tf.tanh(state), state

    def lstm_cell_2(i,o,state):
        if use_dropout:
            i = tf.nn.dropout(i,keep_prob=1.0 - dropout_rate,seed=tf.set_random_seed(54321))
        ifco_x2 = tf.concat(1,[ix2,fx2,cx2,ox2])
        ifco_o2 = tf.concat(1,[im2,fm2,cm2,om2])
        ifco_bias2 = tf.concat(1,[ib2,fb2,cb2,ob2])
        ifco_wx_plus_b_2 = tf.matmul(i,ifco_x2) + tf.matmul(o,ifco_o2) + ifco_bias2
        input_gate_2 = tf.sigmoid(tf.slice(ifco_wx_plus_b_2,[0,0],[-1,num_nodes[1]]))
        forget_gate_2 = tf.sigmoid(tf.slice(ifco_wx_plus_b_2,[0,num_nodes[1]],[-1,num_nodes[1]]))
        update = tf.slice(ifco_wx_plus_b_2,[0,2*num_nodes[1]],[-1,num_nodes[1]])
        state = forget_gate_2 * state + input_gate_2 * tf.tanh(update)
        output_gate = tf.sigmoid(tf.slice(ifco_wx_plus_b_2,[0,3*num_nodes[1]],[-1,num_nodes[1]]))
        return output_gate * tf.tanh(state), state

    # Input data.
    train_emb_data = list()
    train_ohe_data = list()

    for _ in range(num_unrollings):
        train_emb_data.append(
            tf.placeholder(tf.float32, shape=[batch_size,embedding_size]))
        train_ohe_data.append(tf.placeholder(tf.float32, shape=[batch_size,char_vocabulary_size]))

    train_inputs = train_emb_data
    train_labels = train_ohe_data  # labels are inputs shifted by one time step.

    # Unrolled LSTM loop.
    outputs_1,outputs_2 = list(),list()
    output_1,output_2 = saved_output_1,saved_output_2
    state_1,state_2 = saved_state_1,saved_state_2
    for i in train_inputs:
        output_1, state_1 = lstm_cell_1(i, output_1, state_1)
        outputs_1.append(output_1)

    # State saving across unrollings.
    with tf.control_dependencies([saved_output_1.assign(output_1),saved_state_1.assign(state_1)]):
        for i in outputs_1:
            output_2, state_2 = lstm_cell_2(i, output_2, state_2)
            outputs_2.append(output_2)
        with tf.control_dependencies([saved_output_2.assign(output_2),saved_state_2.assign(state_2)]):
            # Classifier.
            logits = tf.nn.xw_plus_b(tf.concat(0, outputs_2), w, b)
            loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits, tf.concat(0, train_labels)))

            #loss = -tf.reduce_mean(tf.reduce_sum(tf.mul(tf.nn.softmax(logits),tf.concat(0, train_labels)),1,keep_dims=True)
            #                       /(tf.reduce_sum(tf.square(tf.nn.softmax(logits)),1,keep_dims=True)*
            #                         tf.reduce_sum(tf.square(tf.concat(0,train_labels)),1,keep_dims=True))
            #                       )

    # Optimizer.
    global_step = tf.Variable(0)
    learning_rate = tf.train.exponential_decay(
        12.0, global_step, 1000, 0.9, staircase=True)
    optimizer = tf.train.GradientDescentOptimizer(learning_rate)
    gradients, v = zip(*optimizer.compute_gradients(loss))
    gradients, _ = tf.clip_by_global_norm(gradients, 1.25)
    optimizer = optimizer.apply_gradients(
        zip(gradients, v), global_step=global_step)

    # Predictions.
    train_prediction = tf.nn.softmax(logits)

    # Sampling and validation eval: batch 1, no unrolling.
    sample_input = tf.placeholder(tf.float32, shape=[1, embedding_size])
    saved_sample_output_1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    saved_sample_state_1 = tf.Variable(tf.zeros([1, num_nodes[0]]))
    saved_sample_output_2 = tf.Variable(tf.zeros([1, num_nodes[1]]))
    saved_sample_state_2 = tf.Variable(tf.zeros([1, num_nodes[1]]))

    reset_sample_state_1 = tf.group(
        saved_sample_output_1.assign(tf.zeros([1, num_nodes[0]])),
        saved_sample_state_1.assign(tf.zeros([1, num_nodes[0]])))
    reset_sample_state_2 = tf.group(
        saved_sample_output_2.assign(tf.zeros([1, num_nodes[1]])),
        saved_sample_state_2.assign(tf.zeros([1, num_nodes[1]])))

    sample_output_1, sample_state_1 = lstm_cell_1(
        sample_input, saved_sample_output_1, saved_sample_state_1
    )

    with tf.control_dependencies([saved_sample_output_1.assign(sample_output_1),
                                saved_sample_state_1.assign(sample_state_1)]):
        sample_output_2, sample_state_2 = lstm_cell_2(
                sample_output_1, saved_sample_output_2, saved_sample_state_2
        )

        with tf.control_dependencies([saved_sample_output_2.assign(sample_output_2),
                                saved_sample_state_2.assign(sample_state_2)]):
            sample_prediction = tf.nn.softmax(tf.nn.xw_plus_b(sample_output_2, w, b))

emb_num_steps = 20001
num_steps = 10001
summary_frequency = 100

with tf.Session(graph=graph) as session:
    tf.initialize_all_variables().run()

    print('Initialized Embedding')
    average_loss = 0
    for step in range(emb_num_steps):
        emb_batch_data, emb_batch_labels = generate_batch(batch_size, skip_window)
        feed_dict = {emb_train_dataset : emb_batch_data, emb_train_labels : emb_batch_labels}
        _, l = session.run([emb_optimizer, emb_loss], feed_dict=feed_dict)
        average_loss += l
        if step % 2000 == 0:
            if step > 0:
                average_loss = average_loss / 2000
                # The average loss is an estimate of the loss over the last 2000 batches.
            print('(Embedding) Average loss at step %d: %f' % (step, average_loss))
            average_loss = 0

    embeddings_ndarray = emb_normalized_embeddings.eval()
    print("Embeddings Shape: ",embeddings_ndarray.shape)
    print("Embedding Max/Min: ",np.min(np.min(embeddings_ndarray)),',',np.max(np.max(embeddings_ndarray)))
    print("Embeddings Mean: ",np.mean(embeddings_ndarray[:5],axis=1))
    print('Initialized')

    mean_loss = 0
    for step in range(num_steps):
        batches = train_batches.next()

        assert len(batches[0])==len(batches[1])
        assert len(batches)==num_unrollings
        feed_dict = dict()

        # unrolling is the number of time steps
        for i in range(num_unrollings):
            feed_dict[train_emb_data[i]] = embeddings_ndarray[batches[i][0][:],:]
            batch_ohe = (np.arange(char_vocabulary_size) == batches[i][1][:,None]).astype(np.float32)
            assert embeddings_ndarray[batches[i][0][:],:].shape[0]==batch_size
            assert np.all(list(np.argmax(batch_ohe,axis=1))==list(batches[i][1][:,None]))

            feed_dict[train_ohe_data[i]] = batch_ohe

        _, l, predictions, lr = session.run(
            [optimizer, loss, train_prediction, learning_rate], feed_dict=feed_dict)
        # print('Size of predictions: %d,%d'%(predictions.shape[0],predictions.shape[1]))
        mean_loss += l
        if step % summary_frequency == 0:
            if step > 0:
                mean_loss = mean_loss / summary_frequency
            # The mean loss is an estimate of the loss over the last few batches.
            print(
                '(LSTM) Average loss at step %d: %f learning rate: %f' % (step, mean_loss, lr))
            mean_loss = 0

            labels = None
            for b,l in batches:
                if labels is None:
                    labels = np.asarray(l)
                else:
                    labels = np.concatenate([labels,l])
            labels = labels.flatten()
            assert labels.shape[0]==num_unrollings*batch_size
            labels_ohe = (np.arange(char_vocabulary_size) == labels[:,None]).astype(np.float32)

            # predictions size is (batch_size*num_unrolling,emb_size)
            # pred_sim is batch_size*num_unrolling, vocab_size
            # pred_sim will act as a probability matrix for each bigram in train batches

            print('Minibatch perplexity: %.2f' % float(np.exp(logprob(predictions, labels_ohe))))

            if step % (summary_frequency * 10) == 0:
                # Generate some samples.
                print('=' * 80)
                # creating 5 sentences
                for _ in range(5):
                    sentence = ''
                    # feed is a probability vector of size embedding vector
                    feed = random_distribution()

                    reset_sample_state_1.run()
                    reset_sample_state_2.run()

                    sentence = reverse_dictionary[np.asscalar(np.argmax(np.dot(feed, embeddings_ndarray.T),axis=1))]
                    #print("Beginning sentense with:|",sentence,'|')
                    for _ in range(79//beam_distance):
                        # prediction size 1 x output_size

                        prediction = sample_prediction.eval({sample_input: feed})
                        if not beam_search:
                            raise NotImplementedError
                        else:
                            # Beam search

                            # find max prob label
                            num_choices = np.max([np.min([5,ceil(float(20000)/float(step+1))]),2])
                            max_lbl_indices = list(np.fliplr(np.argsort(prediction))[0,:num_choices])

                            beam_prediction = dict()
                            for label in max_lbl_indices:
                                beam_bigram = sentence[-1]+id2char(label)
                                beambig_prob = prediction[0,label]
                                if beam_bigram not in dictionary:
                                    prob_args = list(np.fliplr(np.argsort(prediction)).flatten())
                                    prob_i = 1
                                    while beam_bigram not in dictionary:
                                        beam_bigram = sentence[-1]+id2char(prob_args[prob_i])
                                        beambig_prob = prediction[0,prob_args[prob_i]]
                                        #print('bigram,:',beam_bigram,': not found in the dictionary',prob_i)
                                        prob_i += 1

                                beambig_index = dictionary[beam_bigram]
                                beambig_embedding = embeddings_ndarray[beambig_index,:]

                                next_feed = np.asarray(beambig_embedding).reshape(1,-1)
                                prediction = sample_prediction.eval({sample_input: next_feed})
                                beam_prediction[label]=beambig_prob*prediction

                            max_beam = None
                            max_bigram = None
                            for k,v in beam_prediction.items():
                                if max_beam == None or np.max(v)>max_beam:
                                    max_bigram_for_label = id2char(k)+id2char(np.argmax(v))
                                    if max_bigram_for_label in dictionary:
                                        max_beam = np.max(v)
                                        max_bigram = max_bigram_for_label

                            sentence += max_bigram

                            '''if num_choices>1:
                                max_lbl_index = np.random.choice(max_lbl_indices,p=prediction[0,max_lbl_indices]/np.sum(prediction[0,max_lbl_indices]))
                            else:
                                max_lbl_index = max_lbl_indices[0]
                            #max_lbl_index = np.asscalar(np.argmax(prediction))
                            #print('Got prediction:|',id2char(max_lbl_index),'|',max_lbl_index)
                            beam_prediction = np.asarray(prediction)
                            # temporary embedding lookup for max prob label
                            #print('Bigram:|',sentence[-1],'|',id2char(max_lbl_index),'|')
                            bigram_from_prediction = sentence[-1]+id2char(max_lbl_index)
                            if bigram_from_prediction not in dictionary:
                                prob_args = list(np.fliplr(np.argsort(prediction)).flatten())
                                prob_i = 1
                                while bigram_from_prediction not in dictionary:
                                    bigram_from_prediction = sentence[-1]+id2char(prob_args[prob_i])
                                    print('bigram,:',bigram_from_prediction,': not found in the dictionary',prob_i)
                                    prob_i += 1

                            bigram_index_from_prediction = dictionary[bigram_from_prediction]
                            bigram_pred_embedding = embeddings_ndarray[bigram_index_from_prediction,:]

                            next_feed = np.asarray(bigram_pred_embedding).reshape(1,-1)
                            next_bigram = bigram_from_prediction
                            for beam_dist in range(beam_distance):
                                # predict from the max prob label embedding

                                next_prediction = sample_prediction.eval({sample_input: next_feed})

                                next_bigram = bigram_from_prediction[-1]+id2char(np.asscalar(np.argmax(next_prediction)))

                                if next_bigram not in dictionary:
                                    prob_args = list(np.fliplr(np.argsort(beam_prediction)).flatten())
                                    prob_i = 1
                                    while next_bigram not in dictionary:
                                        next_bigram = bigram_from_prediction[-1]+id2char(prob_args[prob_i])
                                        prob_i += 1

                                next_bigram_index = dictionary[next_bigram]
                                next_bigram_embedding = embeddings_ndarray[next_bigram_index,:]
                                next_feed = next_bigram_embedding.reshape(1,-1)
                                # update the beam prediction
                                beam_prediction *= np.asarray(next_prediction)

                            # find max label from beam prediction
                            beam_max_lbl_index = np.asscalar(np.argmax(beam_prediction))
                            #print('Beam prediction:|',id2char(beam_max_lbl_index),'|')

                            bigram_from_beam = sentence[-1]+id2char(beam_max_lbl_index)
                            if bigram_from_beam not in dictionary:
                                prob_args = list(np.fliplr(np.argsort(beam_prediction)).flatten())
                                prob_i = 1
                                while bigram_from_beam not in dictionary:
                                    bigram_from_beam = sentence[-1]+id2char(prob_args[prob_i])
                                    beam_max_lbl_index = prob_args[prob_i]
                                    prob_i += 1

                            beam_pred_embedding = embeddings_ndarray[dictionary[bigram_from_beam],:]
                            feed = np.asarray(beam_pred_embedding).reshape(1,-1)

                            sentence += id2char(beam_max_lbl_index)'''
                            #print('Sentence:|',sentence,'|',beam_max_lbl_index)

                    print(sentence)
                print('=' * 80)
            # Measure validation set perplexity.
            reset_sample_state_1.run()
            reset_sample_state_2.run()

            valid_logprob = 0
            for _ in range(valid_size):
                b = valid_batches.next()

                valid_labels_future = (np.arange(char_vocabulary_size) == b[0][1][:,None]).astype(np.float32)
                predictions = sample_prediction.eval({sample_input: embeddings_ndarray[b[0][0][:],:]})

                valid_logprob = valid_logprob + logprob(predictions, valid_labels_future)
            print('Validation set perplexity: %.2f' % float(np.exp(valid_logprob / valid_size)))