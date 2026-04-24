<img width="100" height="100" alt="image" src="https://github.com/user-attachments/assets/1ea60e4f-5ce9-46f4-b4d6-c71f0323ed7d" />
EEG Foundation Challenge: From Cross-Task to Cross-Subject EEG Decoding
The 2025 EEG Foundation Challenge: From Cross-Task to Cross-Subject EEG Decoding is a biosignal challenge accepted to the NeurIPS 2025 Competition Track. This competition aims to advance the field of EEG decoding by addressing two critical challenges:

Cross-Task Transfer Learning: Developing models that can effectively transfer knowledge from passive EEG tasks to active tasks
Subject Invariant Representation: Creating robust representations that generalize across different subjects while predicting clinical factors
Check out the Challenge paper on arXiv: 10.48550/arXiv.2506.19141

Competition Tasks
<img width="2262" height="1421" alt="image" src="https://github.com/user-attachments/assets/8b4217eb-5160-4eff-9301-dfdb5339bfb1" />
Figure 1: HBN-EEG Dataset and Data split. A. EEG is recorded using a 128-channel system during active tasks (i.e., with user input) or passive tasks. B. The psychopathology and demographic factors. C. The dataset split into Train, Test, and Validation. Details in subsection 1.2 of the proposal.

Challenge 1: Cross-Task Transfer Learning
This supervised learning challenge combines regression and classification objectives. Participants will predict behavioral performance metrics (response time via regression and success rate via classification) from an active experimental paradigm (Contrast Change Detection, CCD) using EEG data from a passive paradigm (Surround Suppression, SuS). Teams can leverage multiple datasets and experimental paradigms to train their models, utilizing unsupervised or self-supervised pretraining to capture latent EEG representations, then fine-tuning for the specific supervised objectives to achieve generalization across subjects and cognitive paradigms. See the Starter Kit for more details.

<img width="1429" height="718" alt="image" src="https://github.com/user-attachments/assets/837200ca-3bbe-427c-9d69-266a998f2e13" />


Challenge 2: Psychopathology Factor Prediction (Subject Invariant Representation)
This supervised regression challenge requires teams to predict four continuous psychopathology scores (p-factor, internalizing, externalizing, and attention) from EEG recordings across multiple experimental paradigms. Teams can employ unsupervised or self-supervised pretraining strategies to learn generalizable neural representations, then adapt these foundation models for the regression targets while maintaining robustness across different subjects and experimental conditions. See the Starter Kit for more details.

<img width="1430" height="753" alt="image" src="https://github.com/user-attachments/assets/59915d50-ee2c-496a-8bac-e4297467a779" />






