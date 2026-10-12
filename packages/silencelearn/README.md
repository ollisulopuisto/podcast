# silencelearn

The silence threshold learned from the stretches a user muted by hand in a
Hindenburg session. No dependencies: one file, standard library only.

It is one file because it is also **shipped**: `colab-transcribe` uploads
`silencelearn.py` next to its Colab script, where the workspace does not
exist. `podcast-magic` imports it like any other package, so the two cannot
drift.

The library knows nothing about `.nhsx` files or audio. It takes tracks of
regions and a `Source` that answers two questions: which words a file has, and
what the level is over an interval. The callers do the reading and the decoding.
