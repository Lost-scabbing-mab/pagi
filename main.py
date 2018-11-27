# Copyright (C) 2018 Project AGI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Experiment framework for training and evaluating COMPONENTS."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import json

import mlflow
import tensorflow as tf

from utils import logger_utils
from utils import generic_utils as util

# Flags
FLAGS = tf.flags.FLAGS

tf.flags.DEFINE_string('workflow', 'workflows.workflow',
                       'The workflow to use for the experiment.'
                       'Refer to the ./workflows/ directory for workflow options.')
tf.flags.DEFINE_string('dataset', 'datasets.mnist_dataset',
                       'The dataset to use for the experiment.'
                       'Refer to the ./datasets/ directory for supported datasets.')
tf.flags.DEFINE_string('dataset_location', 'data',
                       'The location of the dataset. Note that for some sets '
                       'such as mnist, it is downloaded for you, so you can '
                       'leave this blank')
tf.flags.DEFINE_string('hparams_override', None,
                       'The hyperparameters to override for this experiment.')
tf.flags.DEFINE_string('hparams_sweep', None,
                       'Jenkins ONLY - The hyperparameters to override for this run/sweep.')
tf.flags.DEFINE_string('workflow_opts_sweep', None,
                       'Jenkins ONLY - The workflow options to override for this run/sweep.')
tf.flags.DEFINE_string('component', 'components.sparse_conv_autoencoder_component',
                       'The component to use for the experiment.'
                       'Refer to the ./components/ directory for supported components.')
tf.flags.DEFINE_string('logging', 'info',
                       'Verbosity level for logging: debug, info, warning, '
                       'error, critical')
tf.flags.DEFINE_string('checkpoint', None,
                       'A saved checkpoint for evaluation or further training.')
tf.flags.DEFINE_string('checkpoint_load_scope', None,
                       'Choose which variable/name scopes to load using a comma-separated list.')
tf.flags.DEFINE_string('checkpoint_frozen_scope', None,
                       'Choose which variable/name scopes to freeze using a comma-separated list.')

tf.flags.DEFINE_string('summary_dir', None, 'Explicitly defines the experiment summary directory.')
tf.flags.DEFINE_string('experiment_def', None, 'Overrides experiment options from a JSON definition file.')

tf.flags.DEFINE_integer('seed', 42, 'Seed used to control randomness for reproducability.')
tf.flags.DEFINE_integer('batches', 10, 'Number of batches to train for.')
tf.flags.DEFINE_integer('experiment_id', None, 'The experiment identifier generated by MLFlow.')

tf.flags.DEFINE_boolean('evaluate', True, 'Enable evaluation during run loop.')
tf.flags.DEFINE_boolean('train', True, 'Enable training during run loop.')
tf.flags.DEFINE_boolean('summarize', True, 'Enable summaries during training.')
tf.flags.DEFINE_boolean('track', False, 'Track experiment using mlflow.')

# Overrides the default component's hparams
hparams_override = {
}


def run_experiment(exp_config):
  """Setup and execute an experiment workflow with specified options."""
  util.set_logging(FLAGS.logging)

  # Get the component's default HParams, then override
  # -------------------------------------------------------------------------
  component_hparams_override = {}

  # Use code defined hparams
  if FLAGS.component in hparams_override:
    component_hparams_override = hparams_override[FLAGS.component]

  # Override that if defined using flag
  if FLAGS.hparams_override:
    if isinstance(FLAGS.hparams_override, dict):
      component_hparams_override = FLAGS.hparams_override
    else:
      # Unstringy the string formatted dict
      component_hparams_override = ast.literal_eval(FLAGS.hparams_override)

  # Override hparams for this sweep/run
  if FLAGS.hparams_sweep:
    # Unstringy the string formatted dict
    hparams_sweep = ast.literal_eval(FLAGS.hparams_sweep)

    # Selectively override component hparams
    component_hparams_override.update(hparams_sweep)

  # Export settings
  # -------------------------------------------------------------------------
  export_opts = {
      'export_filters': True,
      'export_checkpoint': True,
      'interval_batches': FLAGS.batches
  }

  # Classifier settings
  # -------------------------------------------------------------------------
  classifier_opts = {
      'model': 'logistic',  # Options: logistic, svm
      'unit_range': False,  # Set to True if using SVM
      'interval_batches': FLAGS.batches,
      'hparams': {
          'logistic': {
              'C': [0.01, 0.1, 1.0, 10.0]  # Regularization
          },
          'svm': {
              'C': [1.0, 10.0, 100.0]  # Regularization
          }
      }
  }

  # Checkpoint Options
  # -------------------------------------------------------------------------
  checkpoint_opts = {
      'checkpoint_path': FLAGS.checkpoint,
      'checkpoint_load_scope': FLAGS.checkpoint_load_scope,
      'checkpoint_frozen_scope': FLAGS.checkpoint_frozen_scope
  }

  # OPTIONAL: Override options from an experiment definition file
  # -------------------------------------------------------------------------
  workflow_opts_override = {}

  if exp_config:
    if 'export-options' in exp_config:
      export_opts.update(exp_config['export-options'])
    if 'workflow-options' in exp_config:
      workflow_opts_override.update(exp_config['workflow-options'])
    if 'classifier-options' in exp_config:
      classifier_opts.update(exp_config['classifier-options'])
    if 'checkpoint-options' in exp_config:
      checkpoint_opts.update(exp_config['checkpoint-options'])

  # Override workflow options for this sweep/run
  if FLAGS.workflow_opts_sweep:
    # Unstringy the string formatted dict
    workflow_opts_sweep = ast.literal_eval(FLAGS.workflow_opts_sweep)

    # Selectively override component hparams
    workflow_opts_override.update(workflow_opts_sweep)

  # Training with Tensorflow
  # -------------------------------------------------------------------------
  with tf.Graph().as_default():
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    session = tf.Session(config=config)
    util.set_seed(FLAGS.seed)

    # Load relevant dataset, workflow and component modules
    dataset_class = util.get_module_class_ref(FLAGS.dataset)
    workflow_class = util.get_module_class_ref(FLAGS.workflow)
    component_class = util.get_module_class_ref(FLAGS.component)

    # Override workflow options
    workflow_opts = workflow_class.default_opts()
    workflow_opts.override_from_dict(workflow_opts_override)

    # Log experiment settings
    print('Dataset:', FLAGS.dataset)
    print('Workflow:', FLAGS.workflow)
    print('Component:', FLAGS.component, '\n')

    print('Export Options:', json.dumps(export_opts, indent=4))
    print('Workflow Options:', json.dumps(workflow_opts.values(), indent=4))
    print('Classifier Options:', json.dumps(classifier_opts, indent=4))
    print('Checkpoint Options:', json.dumps(checkpoint_opts, indent=4), '\n')

    # Setup Experiment Workflow
    # -------------------------------------------------------------------------
    workflow = workflow_class(session, dataset_class, FLAGS.dataset_location, component_class,
                              component_hparams_override, classifier_opts, export_opts, opts=workflow_opts,
                              summarize=FLAGS.summarize, seed=FLAGS.seed, summary_dir=FLAGS.summary_dir,
                              checkpoint_opts=checkpoint_opts)

    # Start experiment to train the model and evaluating every N batches
    # -------------------------------------------------------------------------
    workflow.run(FLAGS.batches, evaluate=workflow_opts.evaluate, train=workflow_opts.train)

    session.close()


def main(_):
  # OPTIONAL: Override FLAGS from an experiment definition file
  # Flags set in the experiment definition file have precedent over any flags
  # set by the command line, except FLAGS.hparams_sweep.
  # -------------------------------------------------------------------------
  exp_config = None
  if FLAGS.experiment_def:
    with open(FLAGS.experiment_def) as config_file:
      exp_config = json.load(config_file)

    # Override flags from file
    if 'experiment-options' in exp_config:
      for key, value in exp_config['experiment-options'].items():
        if not key.endswith('_sweep'):  # Don't override sweep parameters
          FLAGS[key].value = value

  if FLAGS.track:
    with mlflow.start_run(experiment_id=FLAGS.experiment_id):
      logger_utils.log_param({'num_batches': FLAGS.batches})

      run_experiment(exp_config)
  else:
    run_experiment(exp_config)


if __name__ == '__main__':
  tf.app.run()
