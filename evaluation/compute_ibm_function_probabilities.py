import glob
import json
import pickle
import numpy as np

# IBM Cloud Code Engine traces (Nasiri et al., EuroSys 2026):
# https://github.com/ubc-cirrus-lab/ibm-cloud-code-engine-traces
# Run its decompress.sh and place the week_*.pickle files in ../trace-data/ibm/data/
DATASET_PATTERN = "../trace-data/ibm/data/week_*.pickle"
RESULTS_FILENAME = "evaluation/ibm_function_probabilities.json"
MAX_FUNCTIONS = 1000


# A week file is several GB of per-request arrays and does not fit in memory.
# The DataFrame is pickled column by column, so stop after the first three:
# NamespaceHash, AppHash, NumEvents.
class ColumnUnpickler(pickle.Unpickler):
    columns = None

    def find_class(self, module, name):
        if name == "_unpickle_block":
            return self.add_column
        return super().find_class(module, name)

    def add_column(self, values, placement, ndim):
        self.columns.append(values[0])
        if len(self.columns) == 3:
            raise StopIteration


def calculate_probability_distribution(functions, counts):
    order = np.argsort(counts)[::-1][:MAX_FUNCTIONS]
    probabilities = counts[order] / np.sum(counts[order])
    return dict(zip(functions[order], probabilities))


if __name__ == "__main__":
    invocations = {}
    for filename in sorted(glob.glob(DATASET_PATTERN)):
        with open(filename, 'rb') as picklefile:
            unpickler = ColumnUnpickler(picklefile)
            unpickler.columns = []
            try:
                unpickler.load()
            except StopIteration:
                pass

        _, app_hashes, num_events = unpickler.columns
        for function, count in zip(app_hashes, num_events):
            invocations[function] = invocations.get(function, 0) + int(count)

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
