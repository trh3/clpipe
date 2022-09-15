from distutils.log import debug
from .batch_manager import LOGGER_NAME, BatchManager, Job
from .config_json_parser import ClpipeConfigParser
import os
import parse
import glob
import sys
import click

from .utils import get_logger, add_file_handler
from .status import needs_processing, write_record
from .config import CONFIG_HELP, DEBUG_HELP, LOG_DIR_HELP, SUBMIT_HELP, CLICK_FILE_TYPE, \
    STATUS_CACHE_HELP, CLICK_FILE_TYPE_EXISTS, CLICK_DIR_TYPE_EXISTS

# These imports are for the heudiconv converter
from pkg_resources import resource_filename
from .error_handler import exception_handler
import logging

COMMAND_NAME = "convert"
STEP_NAME = "bids-conversion"
BASE_CMD = ("dcm2bids -d {dicom_dir} -o {bids_dir} "
            "-p {subject} -c {conv_config_file}")

CONVERSION_CONFIG_HELP = (
    "A dcm2bids conversion definition .json file."
)
HEURISTIC_FILE_HELP = (
    "A heudiconv heuristic file to use for the conversion."
)
DICOM_DIR_HELP = "The folder where subject dicoms are located."
DICOM_DIR_FORMAT_HELP = (
    "Format string for how subjects/sessions are organized within the "
    "dicom_dir."
)
BIDS_DIR_HELP = "The dicom info output file name."
OVERWRITE_HELP = "Overwrite existing BIDS data?"
SUBJECT_HELP = (
    "A subject  to convert using the supplied configuration file. "
    "Use to convert single subjects, else leave empty."
)
SUBJECTS_HELP = (
    "*heudiconv only* - Specify a list of subjects to convert"
)
SESSION_HELP = (
    "A session  to convert using the supplied configuration file. Use in "
    "combination with -subject to convert single subject/sessions, "
    "else leave empty"
)
LONGITUDINAL_HELP = (
    "Convert all subjects/sessions into individual pseudo-subjects. "
    "Use if you do not want T1w averaged across sessions during FMRIprep"
)
MODE_HELP = (
    "Specify which converter to use."
)


@click.command(COMMAND_NAME)
@click.option('-config_file', '-c', type=CLICK_FILE_TYPE_EXISTS, default=None,
              help=CONFIG_HELP)
@click.option('-conv_config_file', type=CLICK_FILE_TYPE_EXISTS, default=None, 
              help=CONVERSION_CONFIG_HELP)
@click.option('-heuristic', '-h', help=HEURISTIC_FILE_HELP)
@click.option('-dicom_dir', '-i', type=CLICK_DIR_TYPE_EXISTS, help=DICOM_DIR_HELP)
@click.option('-dicom_dir_format', help=DICOM_DIR_FORMAT_HELP)
@click.option('-BIDS_dir', '-o', type=CLICK_DIR_TYPE_EXISTS,
              help=BIDS_DIR_HELP)
@click.option('-overwrite', is_flag=True, default=False, help=OVERWRITE_HELP)
@click.option('-log_dir', type=CLICK_DIR_TYPE_EXISTS, help=LOG_DIR_HELP)
@click.option('-subject', required=False, help=SUBJECT_HELP)
@click.option('-subjects', required=False, help=SUBJECTS_HELP)
@click.option('-session', required=False, help=SESSION_HELP)
@click.option('-longitudinal', is_flag=True, default=False,
              help=LONGITUDINAL_HELP)
@click.option('-submit', '-s', is_flag=True, default=False, help=SUBMIT_HELP)
@click.option('-debug', '-d', is_flag=True, help=DEBUG_HELP)
@click.option('-dcm2bids/-heudiconv', default=True, help=MODE_HELP)
@click.option('-status_cache', default=None, type=CLICK_FILE_TYPE, 
              help=STATUS_CACHE_HELP)
def convert2bids_cli(dicom_dir, dicom_dir_format, bids_dir, 
                     conv_config_file, heuristic, dcm2bids,
                     config_file, overwrite, log_dir, subject, subjects, session, 
                     longitudinal, submit, debug, status_cache):
    """Convert DICOM files to BIDS format"""
    convert2bids(
        dicom_dir=dicom_dir, dicom_dir_format=dicom_dir_format, 
        bids_dir=bids_dir, conv_config_file=conv_config_file, heuristic=heuristic,
        config_file=config_file, overwrite=overwrite, log_dir=log_dir, 
        subject=subject, subjects=subjects, session=session, longitudinal=longitudinal, 
        submit=submit, status_cache=status_cache, debug=debug, dcm2bids=dcm2bids)


def convert2bids(dicom_dir=None, dicom_dir_format=None, bids_dir=None, 
                 conv_config_file=None, heuristic=None, config_file=None, overwrite=None, 
                 log_dir=None, subject=None, subjects=None, session=None, longitudinal=False, 
                 status_cache=None, submit=None, debug=False, dcm2bids=True):
    
    config_parser = ClpipeConfigParser()
    config_parser.config_updater(config_file)
    config = config_parser.config

    project_dir = config["ProjectDirectory"]

    add_file_handler(os.path.join(project_dir, "logs"))
    logger = get_logger(STEP_NAME, debug=debug)

    dicom_dir = dicom_dir if dicom_dir else config['DICOMToBIDSOptions']['DICOMDirectory']
    dicom_dir_format = dicom_dir_format if dicom_dir_format else config['DICOMToBIDSOptions']['DICOMFormatString']
    bids_dir = bids_dir if bids_dir else config['DICOMToBIDSOptions']['BIDSDirectory']
    conv_config_file = conv_config_file if conv_config_file else config['DICOMToBIDSOptions']['ConversionConfig']
    log_dir = log_dir if log_dir else config['DICOMToBIDSOptions']['LogDirectory']
    heuristic = heuristic if heuristic else config['DICOMToBIDSOptions']['Heuristic']

    batch_config = config['BatchConfig']
    mem_usage = config['DICOMToBIDSOptions']['MemUsage']
    time_usage = config['DICOMToBIDSOptions']['TimeUsage']
    n_threads = config['DICOMToBIDSOptions']['CoreUsage']

    if not dicom_dir:
        logger.error('DICOM directory not specified.')
        sys.exit(1)
    if not bids_dir:
        logger.error('BIDS directory not specified.')
        sys.exit(1)
    if not dicom_dir_format:
        logger.error('Format string not specified.')
        sys.exit(1)
    if not log_dir:
        logger.error('Log directory not specified.')
        sys.exit(1)

    batch_manager = BatchManager(batch_config, log_dir, debug=debug)
    batch_manager.create_submission_head()
    batch_manager.update_mem_usage(mem_usage)
    batch_manager.update_time(time_usage)
    batch_manager.update_nthreads(n_threads)

    logger.info(f"Starting BIDS conversion targeting: {dicom_dir}")
    logger.debug(f"Using config file: {config_file}")
    
    if dcm2bids:
        logger.info("Using converter: dcm2bids")

        if not conv_config_file:
            logger.error("Must provide a conversion config file when using dcm2bids")
            sys.exit(1)

        config_parser.setup_dcm2bids(
            dicom_dir,
            conv_config_file,
            bids_dir,
            dicom_dir_format,
            log_dir)

        dcm2bids_wrapper(
            dicom_dir=dicom_dir, dicom_dir_format=dicom_dir_format, 
            bids_dir=bids_dir, conv_config=conv_config_file, 
            overwrite=overwrite, log_dir=log_dir, 
            subject=subject, session=session, longitudinal=longitudinal, 
            submit=submit, status_cache=status_cache, debug=debug,
            logger=logger, batch_manager=batch_manager)

    elif not dcm2bids:
        logger.info("Using converter: heudiconv")

        if not heuristic:
            logger.error("Must provide a heuristic file when using heudiconv")
            sys.exit(1)

        config_parser.setup_heudiconv(
            dicom_dir,
            os.path.abspath(heuristic),
            os.path.abspath(bids_dir))

        heudiconv_wrapper(
            subjects=subjects, dicom_directory=dicom_dir, submit=submit,
            output_directory=bids_dir, heuristic_file=heuristic,
            overwrite=overwrite, batch_manager=batch_manager, logger=logger,
            dicom_dir_format=dicom_dir_format)

    else:
        logger.error("Must specificy one of either 'conv_config' or 'heuristic'")


def dcm2bids_wrapper(
    dicom_dir: os.PathLike, 
    bids_dir: os.PathLike, 
    conv_config: os.PathLike, 
    dicom_dir_format: str, 
    batch_manager: BatchManager,
    logger: logging.Logger,
    subject: str=None,
    session: str=None,
    longitudinal: bool=False,
    overwrite: bool=None, 
    status_cache: os.PathLike=None,
    submit: bool=None
    ):

    format_str = dicom_dir_format.replace("{subject}", "*")
    session_toggle = False
    if "{session}" in dicom_dir_format:
        session_toggle = True

    format_str = format_str.replace("{session}", "*")
    logger.debug(f"Format string: {format_str}")

    pstring = os.path.join(dicom_dir, dicom_dir_format+'/')
    logger.debug(f"pstring: {pstring}")
    
    # Get all folders in the dicom_dir
    folders = glob.glob(os.path.join(dicom_dir, format_str+'/'))
    # Parse the subject id and/or session id from the folder names
    sub_sess_list = [parse.parse(pstring, x) for x in folders]

    # Create a list of indexes for both subjects and sessions
    sub_inds = [ind for ind, x in enumerate(sub_sess_list)]
    sess_inds = [ind for ind, x in enumerate(sub_sess_list)]
    
    # Narrow down the index lists to the requested subjects/sessions
    if subject is not None:
        sub_inds = [ind for ind, x in enumerate(sub_sess_list) \
            if x['subject'] == subject]
    if session is not None:
        sess_inds = [ind for ind, x in enumerate(sub_sess_list) \
            if x['session'] == session]

    # Find the intersection of subject and session indexes
    sub_sess_inds = list(set(sub_inds) & set(sess_inds))

    # Pick the relevant folders using the remaining indexes
    folders = [folders[i] for i in sub_sess_inds]
    # Pick the relevant subject sessions using the remaining indexes
    sub_sess_list = [sub_sess_list[i] for i in sub_sess_inds]

    if len(sub_sess_list) == 0:
        logger.error((f'There are no subjects/sessions found for format '
                       'string: {format_str}'))
        sys.exit(1)

    conv_string = BASE_CMD
    if session_toggle and not longitudinal:
        conv_string += " -s {session}"

    if overwrite:
        conv_string = conv_string + " --clobber --forceDcm2niix"

    subjects_to_process = [result['subject'] for result in sub_sess_list]

    # Default to processing all subjects
    subjects_need_processing = subjects_to_process
    # Reduce subjects to process based on cache if provided
    if status_cache:
        # TODO: Handle subject/session
        subjects_need_processing = needs_processing(
            subjects_to_process, status_cache
        )

    # Create jobs using the sub/sess list
    for ind, i in enumerate(sub_sess_list):
        subject = i['subject']

        # Create a dict of args with which to format conv_string
        conv_args = {
            "dicom_dir": folders[ind], 
            "conv_config_file": conv_config,
            "bids_dir": bids_dir,
            "subject": subject
        }
        job_id = 'convert_sub-' + subject

        if session_toggle:
            job_id += '_ses-' + i['session']
            
            if longitudinal:
                conv_args["subject"] += "sess"+ i['session']
            else:
                conv_args["session"] = session

        # Unpack the conv_args
        submission_string = conv_string.format(**conv_args)

        job = Job(job_id, submission_string)

        if subject in subjects_need_processing:
            batch_manager.addjob(job)

    batch_manager.compile_job_strings()
    if submit:
        if len(subjects_need_processing) > 0:
            logger.info(
                f"Converting subject(s): {', '.join(subjects_need_processing)}"
            )
            batch_manager.submit_jobs()
            
            if status_cache:
                for subject in subjects_need_processing:
                    write_record(subject, cache_path = status_cache)
        else:
            logger.info("No subjects need processing.")
    else:
        batch_manager.print_jobs()


def heudiconv_wrapper(
    dicom_directory: os.PathLike,
    output_directory: os.PathLike,
    heuristic_file: os.PathLike,
    dicom_dir_format: str,
    batch_manager: BatchManager,
    logger: logging.Logger,
    subjects: list=None,
    overwrite: bool=False,
    submit: bool=False
    ):
    """
    This command uses heudiconv to convert dicoms into BIDS formatted NiFTI files. 
    Users can specify any number of subjects, or leave subjects blank to convert all 
    subjects. 
    """

    parse_string = dicom_dir_format.replace('/*', '')
    parse_string = parse_string.replace('*', '')

    logger.debug(f"parse_string: {parse_string}")

    if '{session}' in dicom_dir_format:
        session_toggle = True
        all_dicoms = glob.glob(parse_string.format(
            subject = "*",
            session = "*"
        ))
    else:
        session_toggle = False
        all_dicoms = glob.glob(parse_string.format(
            subject="*"
        ))
    
    logger.debug(f"session_toggle: {session_toggle}")
    logger.debug(f"all_dicoms: {all_dicoms}")

    parser = parse.compile(parse_string)

    fileinfo = [parser.parse(x).named for x in all_dicoms if parser.parse(x) is not None]
    logger.debug(f"fileinfo: {fileinfo}")


    if subjects:
        fileinfo = [x for x in fileinfo if x['subject'] in subjects]


    if session_toggle:
        heudiconv_string = '''module add heudiconv \n heudiconv -d {dicomdirectory} -s {subject} '''\
        ''' -ss {sess} -f {heuristic} -o {output_directory} -b --minmeta'''
    else:
        heudiconv_string = '''module add heudiconv \n heudiconv -d {dicomdirectory} -s {subject} ''' \
                           ''' -f {heuristic} -o {output_directory} -b --minmeta'''
    if overwrite:
        heudiconv_string = '''module add heudiconv \n heudiconv -d {dicomdirectory} -s {subject} ''' \
                           ''' -f {heuristic} -o {output_directory} -b --minmeta --overwrite'''
    
    for file in fileinfo:
        subject_id = file['subject']
        subject_id = subject_id.replace('/*', '')
        subject_id = subject_id.replace('*', '')
        if session_toggle:
             session_id = file['session']
             session_id = session_id.replace('/*', '')
             session_id = session_id.replace('*', '')
             job_id = 'convert_sub-' + file['subject'] + '_ses-' + file['session']
             job1 = Job(job_id, heudiconv_string.format(
                dicomdirectory=dicom_directory,
                subject=subject_id,
                sess=session_id,
                heuristic = heuristic_file,
                output_directory = output_directory
            ))
        else:
            job_id = 'convert_sub-' + file['subject']
            job1 = Job(job_id, heudiconv_string.format(
                dicomdirectory=dicom_directory,
                subject=subject_id,
                heuristic=heuristic_file,
                output_directory=os.path.abspath(output_directory)
            ))
        batch_manager.addjob(job1)


    batch_manager.compilejobstrings()
    if submit:
        batch_manager.submit_jobs()
    else:
        batch_manager.print_jobs()


@click.command()
@click.option('-config_file', type=click.Path(exists=True, dir_okay=False, file_okay=True), default = None, help = 'The configuration file for the study, use if you have a custom batch configuration.')
@click.option('-subject', required=True, default=None, help = 'A subject that has all scans of interest present.')
@click.option('-session', default=None, help = 'A session indicator, if sessions are present')
@click.option('-dicom_directory', required = True, help = 'The specially formatted dicom directory string. Please see help pages at https://clpipe.readthedocs.io/en/latest/index.html for more details')
@click.option('-output_file', default = "dicom_info.tsv", help = 'The dicom info output file name.')
@click.option('-submit', is_flag = True, default=False, help = 'Submission job to HPC.')
def dicom_to_nifti_to_bids_converter_setup(subject = None, session = None, dicom_directory=None, output_file=None, config_file = None,  submit=False):
    """This command can be used to compute and extract a dicom information spreadsheet so that a heuristic file can be written. Users should specify a subject with all scans of interest present, and run this command on all sessions of interest. """
    config = ClpipeConfigParser()

    heuristic_file = resource_filename(__name__, 'data/setup_heuristic.py')

    if session:
        heudiconv_string = '''module add heudiconv \n heudiconv -d {dicomdirectory} -s {subject} '''\
        ''' -ss {sess} -f {heuristic} -o ./test/ -b --minmeta \n cp ./test/'''\
        '''.heudiconv/{subject}/ses-{sess}/info/dicominfo_ses-{sess}.tsv {outputfile} \n rm -rf ./test/'''
    else:
        heudiconv_string = '''module add heudiconv \n heudiconv -d {dicomdirectory} -s {subject} ''' \
                           ''' -f {heuristic} -o ./test/ -b --minmeta \n cp ./test/''' \
                           '''.heudiconv/{subject}/info/dicominfo.tsv {outputfile} \n rm -rf ./test/'''

    batch_manager = BatchManager(config.config['BatchConfig'], None)
    batch_manager.update_time('1:0:0')
    batch_manager.update_mem_usage('3000')
    if session:
        job1 = Job("heudiconv_setup", heudiconv_string.format(
            dicomdirectory=os.path.abspath(dicom_directory),
            subject=subject,
            sess=session,
            heuristic = heuristic_file,
            outputfile = os.path.abspath(output_file),
        ))
    else:
        job1 = Job("heudiconv_setup", heudiconv_string.format(
            dicomdirectory=os.path.abspath(dicom_directory),
            subject=subject,
            heuristic = heuristic_file,
            outputfile = os.path.abspath(output_file),
        ))

    batch_manager.addjob(job1)
    batch_manager.compilejobstrings()
    if submit:
        batch_manager.submit_jobs()
    else:
        batch_manager.print_jobs()
