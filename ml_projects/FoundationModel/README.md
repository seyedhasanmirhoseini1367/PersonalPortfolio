Challenge 1: Cross-Task Transfer Learning
This supervised learning challenge consists of a regression task.

Participants will predict behavioral performance metrics (response time via regression) from an active experimental paradigm (Contrast Change Detection, CCD) using EEG data. We suggest that competitors use passive activities as a pretraining and fine-tune into the cognitive task CCD.

Teams can leverage multiple datasets and experimental paradigms to train their models, utilizing unsupervised or self-supervised pretraining to capture latent EEG representations, then fine-tuning for the specific supervised objectives to achieve generalization across subjects and cognitive paradigms. 

Challenge 2: Externalizing Factor Prediction
This supervised regression challenge requires teams to predict the continuous psychopathology score (externalizing) from EEG recordings across multiple experimental paradigms.

Teams can employ unsupervised or self-supervised pretraining strategies to learn generalizable neural representations, then adapt these foundation models for the regression targets while maintaining robustness across different subjects and experimental conditions.

Dataset
The competition uses the HBN-EEG dataset (paper, blog post), which includes EEG recordings from over 3,000 participants across six distinct cognitive tasks:

Passive Tasks
Resting State (RS): Eyes open/closed conditions with fixation cross
Surround Suppression (SuS): Four flashing peripheral disks with contrasting background
Movie Watching (MW): Four short films with different themes

Active Tasks
Contrast Change Detection (CCD): Identifying dominant contrast in co-centric flickering grated disks
Sequence Learning (SL): Memorizing and reproducing sequences of flashed circles
Symbol Search (SyS): Computerized version of WISC-IV subtest
Each participant’s data is accompanied by four psychopathology dimensions derived from the Child Behavior Checklist (CBCL) and demographic information, including age, sex, and handedness. Data is in the BIDS (Brain Imaging Data Structure) format.