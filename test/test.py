"""Validate a face recognizer on the "Labeled Faces in the Wild" dataset (http://vis-www.cs.umass.edu/lfw/).
Embeddings are calculated using the pairs from http://vis-www.cs.umass.edu/lfw/pairs.txt and the ROC curve
is calculated and plotted. Both the model metagraph and the model parameters need to exist
in the same directory, and the metagraph should have the extension '.meta'.
"""
# MIT License
# 
# Copyright (c) 2016 David Sandberg
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import argparse
import sys
sys.path.insert(0,'networks')
sys.path.insert(0,'lib')
import utils
import lfw
import os
import math
import tensorflow.contrib.slim as slim
from tensorflow.contrib.slim.nets import resnet_v1, resnet_v2
#from models import resnet_v1, resnet_v2,resnet_v1_modify,resnet_v2_modify
import sphere_network as network
from sklearn import metrics
from scipy.optimize import brentq
from scipy import interpolate
import importlib
import pdb

def main(args):
  
    with tf.Graph().as_default():
      
        with tf.Session() as sess:
            
            # Read the file containing the pairs used for testing
            pairs = lfw.read_pairs(os.path.expanduser(args.lfw_pairs))
            #pdb.set_trace()

            # Get the paths for the corresponding images
            paths, actual_issame = lfw.get_paths(os.path.expanduser(args.lfw_dir), pairs, args.lfw_file_ext)

            # Load the model
            #facenet.load_model(args.model)
            
            # Get input and output tensors

            
            #image_size = images_placeholder.get_shape()[1]  # For some reason this doesn't work for frozen graphs
            image_size = args.image_size
            print('image size',image_size)
            #images_placeholder = tf.placeholder(tf.float32,shape=(None,image_size,image_size,3),name='image')
            images_placeholder = tf.placeholder(tf.float32,shape=(None,args.image_height,args.image_width,3),name='image')
            phase_train_placeholder = tf.placeholder(tf.bool, name='phase_train')
            #with slim.arg_scope(resnet_v1.resnet_arg_scope(False)):
            if args.network_type == 'resnet50':
                with slim.arg_scope(resnet_v2.resnet_arg_scope(False)):
                    prelogits, end_points = resnet_v2.resnet_v2_50(images_placeholder,is_training=phase_train_placeholder,num_classes=256,output_stride=16)
                    #prelogits, end_points = resnet_v2.resnet_v2_50(images_placeholder,is_training=phase_train_placeholder,num_classes=256,output_stride=8)
                    #prelogits, end_points = resnet_v2_modify.resnet_v2_50(images_placeholder,is_training=phase_train_placeholder,num_classes=256)
                    #prelogits = slim.batch_norm(prelogits, is_training=phase_train_placeholder,epsilon=1e-5, scale=True,scope='softmax_bn')
                    prelogits = tf.squeeze(prelogits,[1,2],name='SpatialSqueeze')
            elif args.network_type == 'inception_resnet_v1':
                prelogits, _ = inception_resnet_v1.inference(images_placeholder,1.0,phase_train=phase_train_placeholder, bottleneck_layer_size=256, weight_decay=0.0)
                pdb.set_trace()
                if args.fc_bn:
                    prelogits = slim.batch_norm(prelogits, is_training=phase_train_placeholder,epsilon=1e-5, scale=True,scope='softmax_bn')
            elif args.network_type == 'sphere_network':
                prelogits = network.infer(images_placeholder)
                if args.fc_bn:
                    prelogits = slim.batch_norm(prelogits, is_training=phase_train_placeholder,epsilon=1e-5, scale=True,scope='softmax_bn')
            elif args.network_type == 'densenet':
                with slim.arg_scope(densenet.densenet_arg_scope(0.0001)):
                    #prelogits, end_points = densenet.densenet_small(images_placeholder,is_training=phase_train_placeholder,num_classes=256)
                    prelogits, end_points = densenet.densenet121(images_placeholder,is_training=phase_train_placeholder,num_classes=256)
                    #prelogits, end_points = densenet.densenet_small_middle(images_placeholder,is_training=phase_train_placeholder,num_classes=256)
                    prelogits = tf.squeeze(prelogits,[1,2],name='SpatialSqueeze')

            
            #embeddings = tf.nn.l2_normalize(prelogits, 1, 1e-10, name='embeddings')
            embeddings = tf.identity(prelogits)
            #saver = tf.train.Saver(tf.trainable_variables(), max_to_keep=3)
            saver = tf.train.Saver(tf.global_variables(), max_to_keep=3)
            saver.restore(sess, args.model)
            if args.save_model:
                saver.save(sess,'./tmp_saved_model',global_step=1)
                return 0
 
            embedding_size = embeddings.get_shape()[1]
            # Run forward pass to calculate embeddings
            print('Runnning forward pass on LFW images')
            batch_size = args.lfw_batch_size
            nrof_images = len(paths)
            nrof_batches = int(math.ceil(1.0*nrof_images / batch_size))
            if args.do_flip:
                embedding_size *= 2
                emb_array = np.zeros((nrof_images, embedding_size))
            else:
                emb_array = np.zeros((nrof_images, embedding_size))
            for i in range(nrof_batches):
                start_index = i*batch_size
                print('handing {}/{}'.format(start_index,nrof_images))
                end_index = min((i+1)*batch_size, nrof_images)
                paths_batch = paths[start_index:end_index]
                #images = facenet.load_data(paths_batch, False, False, image_size,True,image_size)
                #images = facenet.load_data2(paths_batch, False, False, args.image_height,args.image_width,True,)
                images = utils.load_data(paths_batch, False, True, args.image_height,args.image_width,True,(args.image_height,args.image_width))
                feed_dict = { images_placeholder:images, phase_train_placeholder:False }
                feats = sess.run(embeddings, feed_dict=feed_dict)
                if args.do_flip:
                    images_flip = utils.load_data(paths_batch, False, True, args.image_height,args.image_width,True,(args.image_height,args.image_width))
                    feed_dict = { images_placeholder:images_flip, phase_train_placeholder:False }
                    feats_flip = sess.run(embeddings, feed_dict=feed_dict)
                    feats = np.concatenate((feats,feats_flip),axis=1)
                    #feats = (feats+feats_flip)/2
                #images = facenet.load_data(paths_batch, False, False, 160,True,182)
                #images = facenet.load_data(paths_batch, False, False, image_size,src_size=256)
                #feed_dict = { images_placeholder:images, phase_train_placeholder:True}
                #pdb.set_trace()
                #feats = facenet.prewhiten(feats)
                feats = utils.l2_normalize(feats)
                emb_array[start_index:end_index,:] = feats
                #pdb.set_trace()
        
            tpr, fpr, accuracy, val, val_std, far = lfw.evaluate(emb_array, 
                actual_issame, nrof_folds=args.lfw_nrof_folds)

            print('Accuracy: %1.3f+-%1.3f' % (np.mean(accuracy), np.std(accuracy)))
            print('Validation rate: %2.5f+-%2.5f @ FAR=%2.5f' % (val, val_std, far))

            auc = metrics.auc(fpr, tpr)
            print('Area Under Curve (AUC): %1.3f' % auc)
            eer = brentq(lambda x: 1. - x - interpolate.interp1d(fpr, tpr)(x), 0., 1.)
            print('Equal Error Rate (EER): %1.3f' % eer)
            
def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    
    parser.add_argument('lfw_dir', type=str,
        help='Path to the data directory containing aligned LFW face patches.')
    parser.add_argument('--network_type', type=str,
        help='Network structure.',default='resnet50')
    parser.add_argument('--fc_bn', 
        help='wheather bn is followed by fc layer.',default=False,action='store_true')
    parser.add_argument('--save_model', type=bool,
        help='whether save model to disk.',default=False)
    parser.add_argument('--do_flip', type=bool,
        help='wheather flip is used in test.',default=False)
    parser.add_argument('--lfw_batch_size', type=int,
        help='Number of images to process in a batch in the LFW test set.', default=200)
    parser.add_argument('model', type=str, 
        help='Could be either a directory containing the meta_file and ckpt_file or a model protobuf (.pb) file')
    parser.add_argument('--image_size', type=int,
        help='Image size (height, width) in pixels.', default=224)
    parser.add_argument('--image_height', type=int,
        help='Image size (height, width) in pixels.', default=112)
    parser.add_argument('--image_width', type=int,
        help='Image size (height, width) in pixels.', default=96)
    parser.add_argument('--lfw_pairs', type=str,
        help='The file containing the pairs to use for validation.', default='data/pairs.txt')
    parser.add_argument('--lfw_file_ext', type=str,
        help='The file extension for the LFW dataset.', default='png', choices=['jpg', 'png'])
    parser.add_argument('--lfw_nrof_folds', type=int,
        help='Number of folds to use for cross validation. Mainly used for testing.', default=10)
    parser.add_argument('--model_def', type=str,
        help='Model definition. Points to a module containing the definition of the inference graph.', default='models.inception_resnet_v1')
    return parser.parse_args(argv)

if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))