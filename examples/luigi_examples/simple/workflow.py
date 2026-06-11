import os
import luigi

# Modified from: https://luigi.readthedocs.io/en/stable/tasks.html
PATH_OUTPUT = os.environ["PATH_OUTPUT"]


class GenerateWords(luigi.Task):
    scicd = {"image": "python:3.12", "tags": ["pc"]}

    words = luigi.ListParameter(default=("apple", "banana", "grapefruit"))

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/simple/words.txt")

    def run(self):
        # write a dummy list of words to output file
        self.output().makedirs()
        with self.output().open("w") as f:
            for word in self.words:
                f.write(f"{word}\n")


class CountLetters(luigi.Task):
    scicd = {"image": "python:3.12", "tags": ["pc"]}

    def requires(self):
        return GenerateWords()

    def output(self):
        return luigi.LocalTarget(f"{PATH_OUTPUT}/simple/letter_counts.txt")

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
