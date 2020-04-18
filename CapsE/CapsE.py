#! /usr/bin/env python

import tensorflow as tf
import numpy as np
import os
import time
import datetime
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from builddata_softplus import *
from capsuleNet import CapsE


# Parameters
# ==================================================
parser = ArgumentParser("CapsE", formatter_class=ArgumentDefaultsHelpFormatter, conflict_handler='resolve')

parser.add_argument("--data", default="../data/", help="Data sources.")
parser.add_argument("--run_folder", default="./", help="Data sources.")
parser.add_argument("--name", default="WN18RR", help="Name of the dataset.")

parser.add_argument("--embedding_dim", default=100, type=int, help="Dimensionality of character embedding (default: 128)")
parser.add_argument("--filter_size", default=1, type=int, help="Comma-separated filter sizes (default: '3,4,5')")
parser.add_argument("--num_filters", default=400, type=int, help="Number of filters per filter size (default: 128)")
parser.add_argument("--learning_rate", default=0.00001, type=float, help="Learning rate")
parser.add_argument("--batch_size", default=128, type=int, help="Batch Size")
parser.add_argument("--neg_ratio", default=1.0, help="Number of negative triples generated by positive (default: 1.0)")
parser.add_argument("--num_epochs", default=51, type=int, help="Number of training epochs")
parser.add_argument("--savedEpochs", default=10, type=int, help="")
parser.add_argument("--allow_soft_placement", default=True, type=bool, help="Allow device soft device placement")
parser.add_argument("--log_device_placement", default=False, type=bool, help="Log placement of ops on devices")
parser.add_argument("--model_name", default='wn18rr_400_4', help="")
parser.add_argument("--useConstantInit", action='store_true')

parser.add_argument('--iter_routing', default=1, type=int, help='number of iterations in routing algorithm')
parser.add_argument('--num_outputs_selesscondCaps', default=1, type=int, help='')
parser.add_argument('--vec_len_secondCaps', default=10, type=int, help='')
parser.add_argument('--seed', default=1234, type=int, help='')

args = parser.parse_args()
print(args)
# Load data
print("Loading data...")

np.random.seed(args.seed)
tf.set_random_seed(args.seed)

train, valid, test, words_indexes, indexes_words, \
	headTailSelector, entity2id, id2entity, relation2id, id2relation = build_data(path=args.data, name=args.name)
data_size = len(train)
train_batch = Batch_Loader(train, words_indexes, indexes_words, headTailSelector, \
						   entity2id, id2entity, relation2id, id2relation, batch_size=args.batch_size, neg_ratio=args.neg_ratio)

entity_array = np.array(list(train_batch.indexes_ents.keys()))

x_valid = np.array(list(valid.keys())).astype(np.int32)
y_valid = np.array(list(valid.values())).astype(np.float32)

x_test = np.array(list(test.keys())).astype(np.int32)
y_test = np.array(list(test.values())).astype(np.float32)

initialization = []

print("Using initialization.")
initialization = np.empty([len(words_indexes), args.embedding_dim]).astype(np.float32)
initEnt, initRel = init_norm_Vector(args.data + args.name + '/relation2vec' + str(args.embedding_dim) + '.init',
										args.data + args.name + '/entity2vec' + str(args.embedding_dim) + '.init', args.embedding_dim)
for _word in words_indexes:
	if _word in relation2id:
		index = relation2id[_word]
		_ind = words_indexes[_word]
		initialization[_ind] = initRel[index]
	elif _word in entity2id:
		index = entity2id[_word]
		_ind = words_indexes[_word]
		initialization[_ind] = initEnt[index]
	else:
		print('*****************Error********************!')
		break
initialization = np.array(initialization, dtype=np.float32)

assert len(words_indexes) % (len(entity2id) + len(relation2id)) == 0

print("Loading data... finished!")

# Training
# ==================================================
with tf.Graph().as_default():
	session_conf = tf.ConfigProto(allow_soft_placement=args.allow_soft_placement, log_device_placement=args.log_device_placement)
	session_conf.gpu_options.allow_growth = True
	sess = tf.Session(config=session_conf)
	with sess.as_default():
		global_step = tf.Variable(0, name="global_step", trainable=False)
		capse = CapsE(sequence_length=x_valid.shape[1],
							initialization=initialization,
							embedding_size=args.embedding_dim,
							filter_size=args.filter_size,
							num_filters=args.num_filters,
							vocab_size=len(words_indexes),
							iter_routing=args.iter_routing,
							batch_size=2*args.batch_size,
							# num_outputs_secondCaps=args.num_outputs_secondCaps,
							vec_len_secondCaps=args.vec_len_secondCaps,
							useConstantInit=args.useConstantInit
							)

		# Define Training procedure
		#optimizer = tf.contrib.opt.NadamOptimizer(1e-3)
		optimizer = tf.train.AdamOptimizer(learning_rate=args.learning_rate)
		#optimizer = tf.train.RMSPropOptimizer(learning_rate=args.learning_rate)
		#optimizer = tf.train.GradientDescentOptimizer(learning_rate=args.learning_rate)
		grads_and_vars = optimizer.compute_gradients(capse.total_loss)
		train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

		out_dir = os.path.abspath(os.path.join(args.run_folder, "runs_CapsE", args.model_name))
		print("Writing to {}\n".format(out_dir))

		checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
		checkpoint_prefix = os.path.join(checkpoint_dir, "model")
		if not os.path.exists(checkpoint_dir):
			os.makedirs(checkpoint_dir)
		# Initialize all variables
		sess.run(tf.global_variables_initializer())

		def train_step(x_batch, y_batch):
			"""
			A single training step
			"""
			feed_dict = {
				capse.input_x: x_batch,
				capse.input_y: y_batch
			}
			_, step, loss = sess.run([train_op, global_step, capse.total_loss], feed_dict)
			return loss

		num_batches_per_epoch = int((data_size - 1) / args.batch_size) + 1
		for epoch in range(args.num_epochs):
			for batch_num in range(num_batches_per_epoch):
				x_batch, y_batch = train_batch()
				loss = train_step(x_batch, y_batch)
				current_step = tf.train.global_step(sess, global_step)
				#print(loss)
			if epoch > 0:
				if epoch % args.savedEpochs == 0:
					path = capse.saver.save(sess, checkpoint_prefix, global_step=epoch)
					print("Saved model checkpoint to {}\n".format(path))


# python CapsE.py --embedding_dim 100 --num_epochs 31 --num_filters 50 --learning_rate 0.0001 --name FB15k-237 --useConstantInit --savedEpochs 30 --model_name fb15k237_caps1