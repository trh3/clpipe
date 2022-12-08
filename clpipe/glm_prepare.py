"""
Design

Step 1: Load in prototype, identify all needed lines
Step 2: Load in paths for all image files, exclude/include as needed
Step 3: Run through all required image files, construct the file changes
Step 3a: Change prototype and spit out into fsf output folder
Step 4: Launch a feat job for each fsf
"""

import os
import glob
import sys
import nibabel as nib
import pandas as pd
import shutil
from pathlib import Path

from .config_json_parser import GLMConfigParser, ClpipeConfigParser
from .utils import add_file_handler, get_logger
from .config import *
from .errors import ConfoundsNotFoundError, EVFileNotFoundError

STEP_NAME = "prepare"

def glm_prepare(glm_config_file: str=None, level: int=L1,
                model: str=None, debug: bool=False):
    glm_config_parser = GLMConfigParser(glm_config_file)
    glm_config = glm_config_parser.config
    glm_setup_options = glm_config["GLMSetupOptions"]
    parent_config = glm_setup_options["ParentClpipeConfig"]

    config = ClpipeConfigParser()
    config.config_updater(parent_config)

    project_dir = config.config["ProjectDirectory"]
    add_file_handler(os.path.join(project_dir, "logs"))
    logger = get_logger(STEP_NAME, debug=debug)

    if level in VALID_L1:
        level = L1
        setup = 'Level1Setups'
    elif level in VALID_L2:
        level = L2
        setup = 'Level2Setups'
    else:
        logger.error(f"Level must be {L1} or {L2}")
        sys.exit(0)

    logger.info(f"Targeting task-{glm_setup_options['TaskName']} {level} model: {model}")
    logger.info("Propogating fsf files...")

    block = [x for x in glm_config[setup] \
            if x['ModelName'] == str(model)]
    if len(block) is not 1:
        raise ValueError("Model not found, or multiple entries found.")
    model_options = block[0]

    if level == L1:
        _glm_l1_propagate(model_options, glm_setup_options, logger)
    elif level == L2:
        _glm_l2_propagate(model_options, glm_setup_options, logger)


def _glm_l1_propagate(l1_block, glm_setup_options, logger):
    with open(l1_block['FSFPrototype']) as f:
        fsf_file_template=f.readlines()

    output_ind = [i for i,e in enumerate(fsf_file_template) if "set fmri(outputdir)" in e]
    image_files_ind = [i for i,e in enumerate(fsf_file_template) if "set feat_files" in e]
    ev_file_inds = [i for i,e in enumerate(fsf_file_template) if "set fmri(custom" in e]
    confound_file_ind = [i for i,e in enumerate(fsf_file_template) if "set confoundev_files(1)" in e]
    regstandard_ind = [i for i, e in enumerate(fsf_file_template) if "set fmri(regstandard)" in e]
    tps_inds = [i for i, e in enumerate(fsf_file_template) if "set fmri(npts)" in e]
    if l1_block['ImageIncludeList'] is not "" and l1_block['ImageExcludeList'] is not "":
        raise ValueError("Only one of ImageIncludeList and ImageExcludeList should be non-empty")

    image_files = glob.glob(os.path.join(l1_block['TargetDirectory'], "**", "*"+l1_block['TargetSuffix']), recursive = True)

    if l1_block['ImageIncludeList'] is not "":
        image_files = [file_path for file_path in image_files if os.path.basename(file_path) in l1_block['ImageIncludeList']]
        base_names = [os.path.basename(file_path) for file_path in image_files]

        files_not_found = [file for file in base_names if file not in l1_block['ImageIncludeList']]
        if len(files_not_found):
            logger.warning("Did not find the following files: " + str(files_not_found))

    if l1_block['ImageExcludeList'] is not "":
        image_files = [file_path for file_path in image_files if
                       os.path.basename(file_path) not in l1_block['ImageExcludeList']]

    image_files = [file for file in image_files if
                         "task-" + glm_setup_options["TaskName"] in file]

    if not os.path.exists(l1_block['FSFDir']):
        os.mkdir(l1_block['FSFDir'])
    for file in image_files:
        try:
            file_name = os.path.basename(file)

            logger.debug("Creating FSF File for image:" + file_name)
            img_data = nib.load(file)
            total_tps = img_data.shape[3]
            ev_conf = _get_ev_confound_mat(file, l1_block, logger)
            out_dir = os.path.join(l1_block['OutputDir'],file_name.replace("_" + l1_block["TargetSuffix"], ".feat"))
            out_fsf = os.path.join(l1_block['FSFDir'],
                                   file_name.replace("_" + l1_block["TargetSuffix"], ".fsf"))
            new_fsf = fsf_file_template

            new_fsf[tps_inds[0]] = "set fmri(npts) " + str(total_tps) + "\n"
            new_fsf[output_ind[0]] = "set fmri(outputdir) \"" + os.path.abspath(out_dir) + "\"\n"
            new_fsf[image_files_ind[0]] = "set feat_files(1) \"" + os.path.abspath(file) + "\"\n"

            if glm_setup_options['ReferenceImage'] is not "":
                new_fsf[regstandard_ind[0]] = "set fmri(regstandard) \"" + os.path.abspath(glm_setup_options['ReferenceImage']) + "\"\n"
            if l1_block['ConfoundSuffix'] is not "":
                new_fsf[confound_file_ind[0]] = "set confoundev_files(1) \"" + os.path.abspath(ev_conf['Confounds']) + "\"\n"

            for i, e in enumerate(ev_conf['EVs']):
                new_fsf[ev_file_inds[i]] = "set fmri(custom" + str(i +1) + ") \"" + os.path.abspath(e) + "\"\n"

            with open(out_fsf, "w") as fsf_file:
                fsf_file.writelines(new_fsf)

        except (EVFileNotFoundError, ConfoundsNotFoundError) as nfe:
            logger.warn(nfe)


def _get_ev_confound_mat(file, l1_block, logger):

    file_name = os.path.basename(file)

    file_prefix = os.path.basename(file).replace(l1_block["TargetSuffix"], "")

    EV_files = []
    for EV in l1_block['EVFileSuffices']:
        try:
            search_path = os.path.join(l1_block["EVDirectory"],"**",file_prefix + EV)
            logger.debug(f"EV search path: {search_path}")
            search_results = glob.glob((search_path), recursive = True)
            if len(search_results) < 1:
                raise EVFileNotFoundError(f"EV file not found: {EV}")
            elif len(search_results) > 1:
                raise EVFileNotFoundError(f"Found more than one EV file matching pattern: {search_path}")
            EV_files.append(search_results[0])
        except EVFileNotFoundError as evfnfe:
            logger.debug(evfnfe)

    if len(EV_files) is not len(l1_block['EVFileSuffices']):
        raise EVFileNotFoundError((
            f"Did not find enough EV files for image: {file_name}. "
            f"Only found {len(EV_files)} and need "
            f"{len(l1_block['EVFileSuffices'])}"
        ))

    if l1_block["ConfoundSuffix"] is not "":
        search_path = os.path.join(l1_block["ConfoundDirectory"],"**",
            file_prefix + l1_block['ConfoundSuffix'])
        logger.debug(f"Confound search path: {search_path}")
        search_results = glob.glob((search_path), recursive = True)
        if len(search_results) < 1:
            raise ConfoundsNotFoundError(f"Did not find a confound file for image: {file_name}")
        elif len(search_results) > 1:
            raise ConfoundsNotFoundError(f"Found more than one confounds file matching pattern: {search_path}")
        return {"EVs": EV_files, "Confounds": search_results[0]}

    return {"EVs": EV_files}


def _glm_l2_propagate(l2_block, glm_setup_options, logger):
    subject_file = l2_block['SubjectFile']
    prototype_file = l2_block['FSFPrototype']
    
    logger.info(f"Reading subject file: {subject_file}")
    sub_tab = pd.read_csv(subject_file)

    logger.info(f"Opening prototype file: {prototype_file}")
    with open(prototype_file) as f:
        fsf_file_template=f.readlines()

    output_ind = [
        i for i,e in enumerate(fsf_file_template) if "set fmri(outputdir)" in e
    ]
    image_files_ind = [
        i for i,e in enumerate(fsf_file_template) if "set feat_files" in e
    ]
    regstandard_ind = [
        i for i, e in enumerate(fsf_file_template) if "set fmri(regstandard)" in e
    ]

    sub_tab = sub_tab.loc[sub_tab['L2_name'] == l2_block['ModelName']]

    fsf_names = sub_tab.fsf_name.unique()

    if not os.path.exists(l2_block['FSFDir']):
        os.mkdir(l2_block['FSFDir'])

    for fsf in fsf_names:
        try:
            new_fsf = fsf_file_template
            target_dirs = sub_tab.loc[sub_tab["fsf_name"] == fsf].feat_folders
            counter = 1
            logger.info("Creating " + fsf)
            for feat in target_dirs:
                if not os.path.exists(feat):
                    raise FileNotFoundError("Cannot find "+ feat)
                else:
                    _apply_mumford_workaround(feat, logger, remove_reg_standard=True)
                    new_fsf[image_files_ind[counter - 1]] = "set feat_files(" + str(counter) + ") \"" + os.path.abspath(
                        feat) + "\"\n"
                    counter = counter + 1

            out_dir = os.path.join(l2_block['OutputDir'], fsf + ".gfeat")
            new_fsf[output_ind[0]] = "set fmri(outputdir) \"" + os.path.abspath(out_dir) + "\"\n"
            out_fsf = os.path.join(l2_block['FSFDir'],
                                   fsf + ".fsf")

            if glm_setup_options['ReferenceImage'] is not "":
                new_fsf[regstandard_ind[0]] = "set fmri(regstandard) \"" + os.path.abspath(glm_setup_options['ReferenceImage']) + "\"\n"

            with open(out_fsf, "w") as fsf_file:
                fsf_file.writelines(new_fsf)

        except Exception as err:
            logger.exception(err)


def glm_apply_mumford_workaround(glm_config_file=None, 
                                 l1_feat_folders_path=None,
                                 remove_reg_standard=False,
                                 debug=False):

    logger = get_logger(APPLY_MUMFORD_COMMAND_NAME, debug=debug)
    if glm_config_file:
        glm_config = GLMConfigParser(glm_config_file).config
        l1_feat_folders_path = glm_config["Level1Setups"]["OutputDir"]

    logger.info(f"Applying Mumford workaround to: {l1_feat_folders_path}")
    for l1_feat_folder in os.scandir(l1_feat_folders_path):
        if os.path.isdir(l1_feat_folder):
            logger.info(f"Processing L1 FEAT folder: {l1_feat_folder.path}")
            _apply_mumford_workaround(l1_feat_folder, logger,
                remove_reg_standard=remove_reg_standard)

    logger.info(f"Finished applying Mumford workaround.")


def _apply_mumford_workaround(l1_feat_folder, logger, remove_reg_standard=False):
    """
    When using an image registration other than FSL's, such as fMRIPrep's,
    this work-around is necessary to run FEAT L2 analysis in FSL.

    See: https://mumfordbrainstats.tumblr.com/post/166054797696/
        feat-registration-workaround
    """
    l1_feat_folder = Path(l1_feat_folder)
    l1_feat_reg_folder = l1_feat_folder / "reg"

    # Create the reg directory if it doesn't exist
    # This happens if FEAT's preprocessing was not used
    if not l1_feat_reg_folder.exists():
        l1_feat_reg_folder.mkdir()
    else:
        # Remove all of the .mat files in the reg folder
        for mat in l1_feat_reg_folder.glob("*.mat"):
            logger.debug(f"Removing: {mat}")
            os.remove(mat)

    if remove_reg_standard:
        # Delete the reg_standard folder if it exists
        reg_standard_path = l1_feat_folder / "reg_standard"
        if reg_standard_path.exists():
            logger.debug(f"Removing: {reg_standard_path}")
            shutil.rmtree(reg_standard_path)

    try:
        # Grab the FSLDIR environment var to get path to standard matrices
        fsl_dir = Path(os.environ["FSLDIR"])
        identity_matrix_path = fsl_dir / 'etc/flirtsch/ident.mat'
        func_to_standard_path = \
            l1_feat_reg_folder / "example_func2standard.mat"
        mean_func_path = l1_feat_folder / 'mean_func.nii.gz'
        standard_path = l1_feat_reg_folder / "standard.nii.gz"

        # Copy over the standard identity matrix
        logger.debug((
            f"Copying identity matrix {identity_matrix_path}"
            f" to {func_to_standard_path}"))
        shutil.copy(identity_matrix_path, func_to_standard_path)

        # Copy in the mean_func image as the reg folder standard,
        # imitating multiplication with the identity matrix.
        logger.debug(
            f"Copying mean func image {mean_func_path} to {standard_path}")
        shutil.copy(mean_func_path, standard_path)
    except FileNotFoundError as e:
        print(e, "- skipping")



