import csv
import glob
import json
import numpy as np

# Huawei Public Cloud Trace 2025 (Joosen et al., EuroSys 2025), "time series" files:
# https://github.com/sir-lab/data-release/blob/main/README_data_release_2025.md
# Extract the requests/ folder of R1.zip ... R5.zip into ../trace-data/huawei/
# (R<region>/requests/day_<00-30>.csv, requests per minute, one column per funcID).
# A funcID is unique only within its region, so the region is part of the name.
DATASET_PATTERN = "../trace-data/huawei/R*/requests/day_*.csv"
RESULTS_FILENAME = "evaluation/huawei_function_probabilities.json"
MAX_FUNCTIONS = 1000


def calculate_probability_distribution(functions, counts):
    order = np.argsort(counts)[::-1][:MAX_FUNCTIONS]
    probabilities = counts[order] / np.sum(counts[order])
    return dict(zip(functions[order], probabilities))


if __name__ == "__main__":
    invocations = {}
    for filename in sorted(glob.glob(DATASET_PATTERN)):
        region = filename.replace("\\", "/").split("/")[-3]
        with open(filename, 'r', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)
            huawei2025 = np.array([[float(value or 0) for value in row[2:]] for row in reader])

        for function, count in zip(header[2:], huawei2025.sum(axis=0)):
            function = region + "---" + function
            invocations[function] = invocations.get(function, 0) + count

    functions = np.array(list(invocations.keys()))
    counts = np.array(list(invocations.values()))
    probability_distribution = calculate_probability_distribution(functions, counts)

    function_probabilities = {}
    for function in probability_distribution.keys():
        function_probabilities[function] = {
            "probability": probability_distribution[function]
        }

    with open(RESULTS_FILENAME, "w") as file:
        json.dump(function_probabilities, file, indent=4)

    print("Results written to", RESULTS_FILENAME)
