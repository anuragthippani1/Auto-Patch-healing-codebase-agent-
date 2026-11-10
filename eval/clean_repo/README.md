# toolkit

A small, dependency-free Python package used as the AutoPatch evaluation target.
All tests pass on this clean copy. `eval/bugs/NN.patch` each inject one bug.

Run the tests (standard library plus pytest only):

```
python -m pytest
```
