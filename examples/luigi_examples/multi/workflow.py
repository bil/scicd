import os
import luigi

# Modified from: https://luigi.readthedocs.io/en/stable/tasks.html
PATH_OUTPUT = os.environ["PATH_OUTPUT"]


class GenerateWords(luigi.Task):
    words = luigi.ListParameter(default=("apple", "banana", "grapefruit"))

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/multi/words.txt")

    def run(self):
        # write a dummy list of words to output file
        self.output().makedirs()
        with self.output().open("w") as f:
            for word in self.words:
                f.write(f"{word}\n")


class CountLetters(luigi.Task):
    # ========================================
    # This will execute on a different runner!
    # See scicd.yaml
    # ========================================

    def requires(self):
        return GenerateWords()

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/multi/letter_counts.txt")

    def run(self):

        # read in file as list
        with self.input().open("r") as infile:
            words = infile.read().splitlines()

        # write each word to output file with its corresponding letter count
        self.output().makedirs()
        with self.output().open("w") as outfile:
            for word in words:
                outfile.write(
                    "{word} | {letter_count}\n".format(
                        word=word, letter_count=len(word)
                    )
                )
