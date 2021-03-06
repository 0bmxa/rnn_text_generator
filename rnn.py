from datetime import datetime
import nltk
import numpy as np
import operator
import pickle
import sys


unknown_token = "UNKNOWN_TOKEN"
card_start = "START_MESSAGE"
card_end = "END_MESSAGE"

# Read in text file
with open('training_data.txt', 'r') as fp:
    training_data = fp.read()

training_data = unicode(training_data, "utf-8", errors="ignore")

# initial tokenization
tokens = nltk.tokenize.casual_tokenize(training_data)
tokens.append(unknown_token)

# count the word frequencies
word_freq = nltk.FreqDist(tokens)

# Get the most common words and build index_to_word and word_to_index vectors
vocab = word_freq.most_common()  # here we might want to tweak something

index_to_word = [x[0] for x in vocab]
word_to_index = dict([(w, i) for i, w in enumerate(index_to_word)])

vocabulary_size = len(index_to_word)

# generate sentences
sentences = []
sentence = []
for token in tokens:
    sentence.append(token)
    if token == card_end:
        sentences.append(sentence)
        sentence = []

x_train = np.asarray(
    [[word_to_index[w] for w in s[:-1]] for s in sentences])
y_train = np.asarray(
    [[word_to_index[w] for w in s[1:]] for s in sentences])


class RNN(object):

    def __init__(self, word_dim, hidden_dim=80, bptt_truncate=4):
        self.word_dim = word_dim
        self.hidden_dim = hidden_dim
        self.bptt_truncate = bptt_truncate

        self.U = np.random.uniform(
            -np.sqrt(1./word_dim),
            np.sqrt(1./word_dim), (hidden_dim, word_dim))
        self.V = np.random.uniform(
            -np.sqrt(1./hidden_dim),
            np.sqrt(1./hidden_dim), (word_dim, hidden_dim))
        self.W = np.random.uniform(
            -np.sqrt(1./hidden_dim),
            np.sqrt(1./hidden_dim), (hidden_dim, hidden_dim))

    def forward_propagation(self, x):
        T = len(x)
        s = np.zeros((T + 1, self.hidden_dim))
        s[-1] = np.zeros(self.hidden_dim)
        o = np.zeros((T, self.word_dim))

        for t in np.arange(T):
            s[t] = np.tanh(self.U[:, x[t]] + self.W.dot(s[t-1]))
            o[t] = self.softmax(self.V.dot(s[t]))
        return [o, s]

    def softmax(self, w, t=1.0):
        e = np.exp(np.array(w) / t)
        dist = e / np.sum(e)
        return dist

    def predict(self, x):
        o, s = self.forward_propagation(x)
        return np.argmax(o, axis=1)

    def calculate_total_loss(self, x, y):
        L = 0
        for i in np.arange(len(y)):
            o, s = self.forward_propagation(x[i])
            correct_word_predictions = o[np.arange(len(y[i])), y[i]]
            L += -1 * np.sum(np.log(correct_word_predictions))
        return L

    def calculate_loss(self, x, y):
        N = np.sum((len(y_i) for y_i in y))
        return self.calculate_total_loss(x, y)/N

    def bptt(self, x, y):
        T = len(y)
        # Perform forward propagation
        o, s = self.forward_propagation(x)
        # We accumulate the gradients in these variables
        dLdU = np.zeros(self.U.shape)
        dLdV = np.zeros(self.V.shape)
        dLdW = np.zeros(self.W.shape)
        delta_o = o
        delta_o[np.arange(len(y)), y] -= 1.
        # For each output backwards...
        for t in np.arange(T)[::-1]:
            dLdV += np.outer(delta_o[t], s[t].T)
            # Initial delta calculation
            delta_t = self.V.T.dot(delta_o[t]) * (1 - (s[t] ** 2))
            # Backpropagation through time
            for bptt_step in np.arange(max(0, t-self.bptt_truncate), t+1)[::-1]:  # noqa
                dLdW += np.outer(delta_t, s[bptt_step-1])
                dLdU[:, x[bptt_step]] += delta_t
                # Update delta for next step
                delta_t = self.W.T.dot(delta_t) * (1 - s[bptt_step-1] ** 2)
        return [dLdU, dLdV, dLdW]

    def gradient_check(self, x, y, h=0.001, error_threshold=0.01):
        # Calculate the gradients using backpropagation.
        # We want to checker if these are correct.
        bptt_gradients = self.bptt(x, y)
        # List of all parameters we want to check.
        model_parameters = ['U', 'V', 'W']
        # Gradient check for each parameter
        for pidx, pname in enumerate(model_parameters):
            # Get the actual parameter value from the mode, e.g. model.W
            parameter = operator.attrgetter(pname)(self)
            print (
                "Performing gradient check for parameter %s"
                "with size %d." % (pname, np.prod(parameter.shape)))
            # Iterate over each element of the parameter matrix
            # , e.g. (0,0), (0,1), ...
            it = np.nditer(
                parameter, flags=['multi_index'], op_flags=['readwrite'])
            while not it.finished:
                ix = it.multi_index
                # Save the original value so we can reset it later
                original_value = parameter[ix]
                # Estimate the gradient using (f(x+h) - f(x-h))/(2*h)
                parameter[ix] = original_value + h
                gradplus = self.calculate_total_loss([x], [y])
                parameter[ix] = original_value - h
                gradminus = self.calculate_total_loss([x], [y])
                estimated_gradient = (gradplus - gradminus)/(2*h)
                # Reset parameter to original value
                parameter[ix] = original_value
                # The gradient for this parameter
                # calculated using backpropagation
                backprop_gradient = bptt_gradients[pidx][ix]
                # calculate The relative error: (|x - y|/(|x| + |y|))
                relative_error = (
                    np.abs(backprop_gradient - estimated_gradient) /
                    (np.abs(backprop_gradient) + np.abs(estimated_gradient)))
                # If the error is to large fail the gradient check
                if relative_error > error_threshold:
                    print ("Gradient Check ERROR:"
                           "parameter=%s ix=%s"
                           % (pname, ix))
                    print("+h Loss: %f" % gradplus)
                    print("-h Loss: %f" % gradminus)
                    print("Estimated_gradient: %f" % estimated_gradient)
                    print("Backpropagation gradient: %f" % backprop_gradient)
                    print("Relative Error: %f" % relative_error)
                    return
                it.iternext()
            print("Gradient check for parameter %s passed." % (pname))

    def sgd_step(self, x, y, learning_rate):
        dLdU, dLdV, dLdW = self.bptt(x, y)
        # Change parameters according to gradients and learning rate
        self.U -= learning_rate * dLdU
        self.V -= learning_rate * dLdV
        self.W -= learning_rate * dLdW


def train_with_sgd(model, X_train, y_train,
                   learning_rate=0.005, nepoch=100, evaluate_loss_after=5):
    # We keep track of the losses so we can plot them later
    losses = []
    num_examples_seen = 0
    for epoch in range(nepoch):
        # Optionally evaluate the loss
        if (epoch % evaluate_loss_after == 0):
            loss = model.calculate_loss(X_train, y_train)
            losses.append((num_examples_seen, loss))
            time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print ("%s: Loss after num_examples_seen="
                   "%d epoch=%d: %f" % (time, num_examples_seen, epoch, loss))
            pickle.dump(model, open("model.p", "wb"))
            # Adjust the learning rate if loss increases
            if (len(losses) > 1 and losses[-1][1] > losses[-2][1]):
                learning_rate = learning_rate * 0.5
                print("Setting learning rate to %f" % learning_rate)
            sys.stdout.flush()
        # For each training example...
        for i in range(len(y_train)):
            # One SGD step
            model.sgd_step(X_train[i], y_train[i], learning_rate)
            num_examples_seen += 1


np.random.seed(15)
model = RNN(vocabulary_size)
o, s = model.forward_propagation(x_train[10])

predictions = model.predict(x_train[10])

print("Expected Loss for random predictions: %f" % np.log(vocabulary_size))
print("Actual loss: %f" % model.calculate_loss(x_train[:1000], y_train[:1000]))

# train
"""
np.random.seed(10)
model = RNN(vocabulary_size)
train_with_sgd(model, x_train, y_train, nepoch=100, evaluate_loss_after=1)
"""


def generate_sentence(model):
    # We start the sentence with the start token
    ns = ['nice', card_end, card_start]
    new_sentence = [word_to_index[i] for i in ns]
    # Repeat until we get an end token
    while not new_sentence[-1] == word_to_index[card_end]:
        o, s = model.forward_propagation(new_sentence)
        sampled_word = word_to_index[unknown_token]
        # We don't want to sample unknown words
        while sampled_word == word_to_index[unknown_token]:
            samples = np.random.multinomial(10, o[-1])
            sampled_word = np.argmax(samples)
        new_sentence.append(sampled_word)
    try:
        sentence_str = [index_to_word[x] for x in new_sentence[1:-1]]
    except IndexError:
        return []
    return sentence_str


# load
model = pickle.load(open("model.p", "rb"))

# retrain
# model = pickle.load(open("model.p", "rb"))
# train_with_sgd(model, x_train, y_train, nepoch=1000, evaluate_loss_after=10)

num_sentences = 10
senten_min_length = 3

for i in range(num_sentences):
    sent = []
    # We want long sentences, not sentences with one or two words
    while len(sent) < senten_min_length:
        sent = generate_sentence(model)
    print(" ".join(sent) + " :computer:")
    print("")
