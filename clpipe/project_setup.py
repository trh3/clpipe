import os
import click
from .config_json_parser import ClpipeConfigParser
from pkg_resources import resource_stream
import json
from .template_flow import _templateflow_setup
import datalad.api


@click.command()
@click.option('-project_title', required=True, default=None)
@click.option('-project_dir', required = True ,type=click.Path(exists=False, dir_okay=True, file_okay=True), default=None,
              help='Where the project will be located.')
@click.option('-source_data', type=click.Path(exists=True, dir_okay=True, file_okay=False),
              help='Where the raw data (usually DICOMs) are located.')
@click.option('-move_source_data', is_flag = True, default = False,
              help='Move source data into project/data_DICOMs folder. USE WITH CAUTION.')
@click.option('-symlink_source_data', is_flag = True, default = False,
              help = 'symlink the source data into project/data_dicoms. Usually safe to do.')
def project_setup(project_title = None, project_dir = None, source_data = None, move_source_data = None,
                  symlink_source_data = None):

    config = ClpipeConfigParser()
    org_source = os.path.abspath(source_data)
    if move_source_data or symlink_source_data:
        source_data = os.path.join(os.path.abspath(project_dir), 'data_DICOMs')
    config.setup_project(project_title, project_dir, source_data)
    if symlink_source_data:
        os.symlink(os.path.abspath(org_source), os.path.join(os.path.abspath(project_dir), 'data_DICOMs'))
    bids_dir = config.config['DICOMToBIDSOptions']['BIDSDirectory']
    datalad.api.run(cmd = 'dcm2bids_scaffold -o '+bids_dir, message = 'Setting up BIDS scaffold', dataset = bids_dir)
    config.config_json_dump(config.config['ProjectDirectory'], 'clpipe_config.json')

    with resource_stream(__name__, 'data/defaultConvConfig.json') as def_conv_config:
        conv_config = json.load(def_conv_config)

    with open(config.config['DICOMToBIDSOptions']['ConversionConfig'], 'w') as fp:
        json.dump(conv_config, fp, indent = '\t')

    os.makedirs(os.path.join(config.config['ProjectDirectory'], 'analyses'), exist_ok=True)
    os.makedirs(os.path.join(config.config['ProjectDirectory'], 'scripts'), exist_ok=True)
    datalad.api.save(path = config.config["ProjectDirectory"], recursive = True)
    #print(os.path.join(os.path.abspath(project_dir), 'clpipe_config.json'))
    #_templateflow_setup(os.path.join(os.path.abspath(project_dir), 'clpipe_config.json'))
