import pandas as pd


TRAIN_PATH = "D:\\datasets\\playground-series-s6\\playground-series-s6e5\\data\\train.csv"
TEST_PATH = "D:\\datasets\\playground-series-s6\\playground-series-s6e5\\data\\test.csv"
SUBMISSION_PATH = "D:\\datasets\\playground-series-s6\\playground-series-s6e5\\data\\sample_submission.csv"


df = pd.read_csv(TRAIN_PATH)
test_df = pd.read_csv(TEST_PATH)
print(df.head())


df.info()

cat_cols = df.select_dtypes(include="object").columns