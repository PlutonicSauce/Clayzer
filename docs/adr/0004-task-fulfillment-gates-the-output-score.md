# Task fulfillment gates the Output Score

Where a Rubric combines weighted criteria into one Output Score, the combined score is capped at the score of any criterion marked as a Gate, and the uncapped weighted mean is still reported alongside it. Without the cap, a Run that delivered nothing but explained its failure well can rank near Runs that did the work; the Gate keeps manner from outweighing substance. The caption Rubric has no weights yet and reports each criterion separately (CAP-15), so no combined score exists to cap; this applies once Clay sets weights.
