from __future__ import absolute_import
from __future__ import print_function

import tensorflow as tf
import sys
sys.path.insert(0, "/home/haojieyuan/autoAdv/benchmark/models/research/slim")
import os

from nets import inception
from nets import nets_factory

slim = tf.contrib.slim


tf.app.flags.DEFINE_integer(
    'batch_size', 64, 'The number of samples in each batch.')

tf.app.flags.DEFINE_string(
    'checkpoint_path', './ckpts/',
    'The directory where the model was written to or an absolute path to a '
    'checkpoint file.')

tf.app.flags.DEFINE_integer(
    'num_preprocessing_threads', 4,
    'The number of threads used to create the batches.')

tf.app.flags.DEFINE_string(
    'dataset_name', 'oxfordFlowers', 'oxfordFlowers, fgvcAircraft, stanfordCars.')


tf.app.flags.DEFINE_string(
    'model_name', 'inception_v3',
    'Name of the model to use, either "inception_v3" "inception_v4" "resnet_v2" or "inception_resnet_v2"')

tf.app.flags.DEFINE_float(
    'weight_decay', 0.00004, 'The weight decay on the model weights.')

tf.app.flags.DEFINE_float(
    'label_smoothing', 0.0, 'The amount of label smoothing.')

tf.app.flags.DEFINE_string(
    'log_dir', './log/',
    'Directory where checkpoints and event logs are written to.')


tf.app.flags.DEFINE_integer('max_number_of_steps', None,
                            'The maximum number of training steps.')

tf.app.flags.DEFINE_integer(
    'log_every_n_steps', 10,
    'The frequency with which logs are print.')

tf.app.flags.DEFINE_integer(
    'save_summaries_secs', 600,
    'The frequency with which summaries are saved, in seconds.')

tf.app.flags.DEFINE_integer(
    'save_interval_secs', 600,
    'The frequency with which the model is saved, in seconds.')


# For Fintune.
tf.app.flags.DEFINE_string(
    'checkpoint_path', None,
    'The path to a checkpoint from which to fine-tune.')

tf.app.flags.DEFINE_string(
    'checkpoint_exclude_scopes', None,
    'Comma-separated list of scopes of variables to exclude when restoring '
    'from a checkpoint.')

tf.app.flags.DEFINE_string(
    'trainable_scopes', None,
    'Comma-separated list of scopes to filter the set of variables to train.'
    'By default, None would train all the variables.')

tf.app.flags.DEFINE_boolean(
    'ignore_missing_vars', False,
    'When restoring a checkpoint would ignore missing variables.')


FLAGS = tf.app.flags.FLAGS


def get_dataset(dataset_name, partition):
    if dataset_name == 'oxfordFlowers':
        dataset_prefix = '/home/haojieyuan/Data/OxfordFlowers'

    elif dataset_name == 'fgvcAircraft':
        dataset_prefix = '/home/haojieyuan/Data/FGVC_Aircraft'

    elif dataset_name == 'stanfordCars':
        dataset_prefix = '/home/haojieyuan/Data/stanfordCars'

    else:
        assert False, 'Unknown dataset name.'

    file_name = os.path.join(dataset_prefix, partition+'.tfrecords')
    reader = tf.TFRecordReader
    keys_to_feature = {
        "img_raw":tf.FixedLenFeature(shape=(),dtype=tf.string),
        "image_format":tf.FixedLenFeature((), tf.string, default_value='raw'),
        "label":tf.FixedLenFeature(shape=(),dtype=tf.int64)
    }
    items_to_handlers = {
        'image': slim.tfexample_decoder.Image(image_key='img_raw', format_key='image_format'),
        'label': slim.tfexample_decoder.Tensor('label')
    }
    decoder=slim.tfexample_decoder.TFExampleDecoder(keys_to_feature, items_to_handlers)

    _ITEMS_TO_DESCRIPTIONS = {
        'image': 'A color image of varying height and width.',
        'label': 'The label id of the image, interger between 0 and class_num-1.'
    }

    return slim.dataset.Dataset(
        data_sources=file_name,reader=reader,decoder=decoder,
        num_samples=sample_num, items_to_descriptions=_ITEMS_TO_DESCRIPTIONS,
        num_classes=NUM_CLASSES)


def preprocess_for_eval(image):
    # make it same as ImageNet
    height = 299
    width = 299
    with tf.name_scope(scope, 'eval_image', [image, height, width]):
        if image.dtype != tf.float32:
            image = tf.image.convert_image_dtype(image, dtype=tf.float32)

    image = tf.reshape(tensor=image, shape=[height, width, 3])

    if height and width:
        image = tf.expand_dims(image, 0)
        image = tf.image.resize_bilinear(image, [height, width],
                                         align_corners=False)
        image = tf.squeeze(image, [0])

    image = tf.subtract(image, 0.5)
    image = tf.multiply(image, 2.0)

    return image


def _get_variables_to_train():
    """Returns a list of variables to train.
       Returns:
       A list of variables to train by the optimizer.
    """
    if FLAGS.trainable_scopes is None:
        return tf.trainable_variables()
    else:
        scopes = [scope.strip() for scope in FLAGS.trainable_scopes.split(',')]
    variables_to_train = []

    for scope in scopes:
        variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope)\
        variables_to_train.extend(variables)

    return variables_to_train


def _get_init_fn():
    """Returns a function run by the chief worker to warm-start the training.
    Note that the init_fn is only run when initializing the model during the very
    first global step.
    Returns:
    An init function run by the supervisor.
    """
    if FLAGS.checkpoint_path is None:
        return None

    # Warn the user if a checkpoint exists in the train_dir. Then we'll be
    # ignoring the checkpoint anyway.
    if tf.train.latest_checkpoint(FLAGS.train_dir):
        tf.logging.info(
            'Ignoring --checkpoint_path because a checkpoint already exists in %s'
            % FLAGS.train_dir)
        return None

    exclusions = []
    if FLAGS.checkpoint_exclude_scopes:
        exclusions = [scope.strip()
                      for scope in FLAGS.checkpoint_exclude_scopes.split(',')]


    variables_to_restore = []
    for var in slim.get_model_variables():
        for exclusion in exclusions:
            if var.op.name.startswith(exclusion):
                break
            else:
                variables_to_restore.append(var)

    if tf.gfile.IsDirectory(FLAGS.checkpoint_path):
        checkpoint_path = tf.train.latest_checkpoint(FLAGS.checkpoint_path)
    else:
        checkpoint_path = FLAGS.checkpoint_path

    tf.logging.info('Fine-tuning from %s' % checkpoint_path)

    return slim.assign_from_checkpoint_fn(checkpoint_path, variables_to_restore,
                                          ignore_missing_vars=FLAGS.ignore_missing_vars)


def main(_):
    tf.logging.set_verbosity(tf.logging.INFO)

    with tf.Graph().as_default():
        #tf_global_step = tf.train.get_or_create_global_step()


        # Data preparation: Train Part.
        train_dataset = get_dataset(FLAGS.dataset_name, 'train')
        train_provider = slim.dataset_data_provider.DatasetDataProvider(
            train_dataset, shuffle=True, common_queue_capacity=2*FLAGS.batch_size,
            common_queue_min=FLAGS.batch_size)
        train_image, train_label = train_provider.get(['image', 'label'])
        train_image = preprocess_for_eval(train_image)
        train_images, train_labels = tf.train.batch(
            [train_image, train_label], batch_size=FLAGS.batch_size,
            num_threads=FLAGS.num_preprocessing_threads,
            capacity=5*FLAGS.batch_size)


        # Data prparation: Test Part.
        test_dataset = get_dataset(FLAGS.dataset_name, 'test')
        test_provider  = slim.dataset_data_provider.DatasetDataProvider(
            test_dataset, shuffle=False, common_queue_capacity=2*FLAGS.batch_size,
            common_queue_min=FLAGS.batch_size)
        test_image, test_label = test_provider.get(['image', 'label'])
        test_image = preprocess_for_eval(test_image)
        test_images, test_labels = tf.train.batch(
            [test_image, test_label], batch_size=FLAGS.batch_size,
            num_threads=FLAGS.num_preprocessing_threads,
            capacity=5*FLAGS.batch_size)


        # Model Defination.
        if FLAGS.dataset_name == 'oxfordFlowers':
            class_num = 102
        elif FLAGS.dataset_name == 'fgvcAircraft':
            class_num = 100
        elif FLAGS.dataset_name == 'stanfordCars':
            class_num = 196
        else:
            assert False, 'Unknown dataset name.'

        network_fn = nets_factory.get_network_fn(
            FLAGS.model_name,
            num_classes=(dataset.num_classes),
            weight_decay=FLAGS.weight_decay,
            is_training=True)

        logits, end_points = network_fn(train_images)


        # Loss Defination.
        if 'AuxLogits' in end_points:
            slim.losses.softmax_cross_entropy(
                end_points['AuxLogits'], train_labels,
                label_smoothing=FLAGS.label_smoothing, weights=0.4)

        slim.losses.softmax_cross_entropy(
            logits, labels, label_smoothing=FLAGS.label_smoothing, weights=1.0)


        # Summary Initialization.
        summaries = set(tf.get_collection(tf.GraphKeys.SUMMARIES))
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        for end_point in end_points:
            x = end_points[end_point]
            summaries.add(tf.summary.histogram('activations/' + end_point, x))
            summaries.add(tf.summary.scalar('sparsity/' + end_point,
                                      tf.nn.zero_fraction(x)))

        for loss in tf.get_collection(tf.GraphKeys.LOSSES):
            summaries.add(tf.summary.scalar('losses/%s' % loss.op.name, loss))

        for variable in slim.get_model_variables():
            summaries.add(tf.summary.histogram(variable.op.name, variable))


        # Optimization Configuration.
        lr = tf.constant(1e-4, name='fixed_learning_rate') # For adam
        optimizer = tf.train.AdamOptimizer(lr, beta1=0.9, beta2=0.999, epsilon=1.0)
        variables_to_train = _get_variables_to_train()

        total_loss = tf.add_n([loss for loss in tf.get_collection(tf.GraphKeys.LOSSES)])
        grad = optimizer.compute_gradients(total_loss)
        grad_updates = optimizer.apply_gradients(grad)
        update_ops.append(grad_updates)
        update_op = tf.group(*update_ops)

        with tf.control_dependencies([update_op]):
            train_tensor = tf.identity(total_loss, name='train_op')


        # Some other summary.
        summaries.add(tf.summary.scalar('total_loss', total_loss))
        summary_op = tf.summary.merge(list(summaries), name='summary_op')


        # Start Training.
        slim.learning.train(
            train_tensor,
            logdir=FLAGS.log_dir,
            init_fn=_get_init_fn(),
            summary_op=summary_op,
            number_of_steps=FLAGS.max_number_of_steps,
            log_every_n_steps=FLAGS.log_every_n_steps,
            save_summaries_secs=FLAGS.save_summaries_secs,
            save_interval_secs=FLAGS.save_interval_secs
            )



if __name__ == '__main__':
    tf.app.run()

