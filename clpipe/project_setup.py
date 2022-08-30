import os
import click
from .config_json_parser import ClpipeConfigParser
from pkg_resources import resource_stream
import json

from .config import DEFAULT_CONFIG_PATH, DEFAULT_CONFIG_FILE_NAME, \
    CLICK_DIR_TYPE_NOT_EXIST, CLICK_DIR_TYPE_EXISTS

COMMAND_NAME = "project_setup"
DEFAULT_DICOM_DIR = 'data_DICOMs'
DCM2BIDS_SCAFFOLD_TEMPLATE = 'dcm2bids_scaffold -o {}'

PROJECT_DIR_HELP = "Where the project will be located."
SOURCE_DATA_HELP = \
    "Where the raw data (usually DICOMs) are located."
MOVE_SOURCE_DATA_HELP = \
    "Move source data into project/data_DICOMs folder. USE WITH CAUTION."
SYM_LINK_HELP = \
    "Symlink the source data into project/data_dicoms. Usually safe to do."


@click.command(COMMAND_NAME)
@click.option('-project_title', required=True, default=None)
@click.option('-project_dir', required=True ,type=CLICK_DIR_TYPE_NOT_EXIST,
              default=None, help=PROJECT_DIR_HELP)
@click.option('-source_data', type=CLICK_DIR_TYPE_EXISTS,
              help=SOURCE_DATA_HELP)
@click.option('-move_source_data', is_flag=True, default=False,
              help=MOVE_SOURCE_DATA_HELP)
@click.option('-symlink_source_data', is_flag=True, default=False,
              help=SYM_LINK_HELP)
def project_setup_cli(project_title=None, project_dir=None, source_data=None, 
                      move_source_data=None, symlink_source_data=None):
    """Set up a clpipe project"""

    project_setup(
        project_title=project_title, 
        project_dir=project_dir, source_data=source_data, 
        move_source_data=move_source_data,
        symlink_source_data=symlink_source_data)


def project_setup(project_title=None, project_dir=None, 
                  source_data=None, move_source_data=None,
                  symlink_source_data=None):

    config_parser = ClpipeConfigParser()

    org_source = os.path.abspath(source_data)
    if move_source_data or symlink_source_data:
        source_data = os.path.join(os.path.abspath(project_dir), 
            DEFAULT_DICOM_DIR)

    config_parser.setup_project(project_title, project_dir, source_data)

    config = config_parser.config

    # Create the project directory
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)

    bids_dir = config['DICOMToBIDSOptions']['BIDSDirectory']
    project_dir = config['ProjectDirectory']
    conv_config_path = config['DICOMToBIDSOptions']['ConversionConfig']
    
    if symlink_source_data:
        os.symlink(
            os.path.abspath(org_source),
            os.path.join(os.path.abspath(project_dir), DEFAULT_DICOM_DIR)
        )
    
    # Create an empty BIDS directory
    os.system(DCM2BIDS_SCAFFOLD_TEMPLATE.format(bids_dir))

    config_parser.config_json_dump(project_dir, DEFAULT_CONFIG_FILE_NAME)

    with resource_stream(__name__, DEFAULT_CONFIG_PATH) as def_conv_config:
        conv_config = json.load(def_conv_config)

    with open(conv_config_path, 'w') as fp:
        json.dump(conv_config, fp, indent='\t')

    os.makedirs(os.path.join(project_dir, 'analyses'), 
                exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'scripts'), 
                exist_ok=True)
