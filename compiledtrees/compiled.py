from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals
from __future__ import print_function

from sklearn.tree.tree import DecisionTreeRegressor, DTYPE
from sklearn.ensemble.gradient_boosting import GradientBoostingRegressor
from sklearn.ensemble.forest import ForestRegressor

from compiledtrees import _compiled
from compiledtrees import code_gen as cg
import numpy as np


class CompiledRegressionPredictor(object):
    """Class to construct a compiled predictor from a previously trained
    ensemble of decision trees.

    Parameters
    ----------

    clf:
      A fitted regression tree/ensemble.

    References
    ----------

    http://courses.cs.washington.edu/courses/cse501/10au/compile-machlearn.pdf
    http://crsouza.blogspot.com/2012/01/decision-trees-in-c.html
    """
    def __init__(self, clf):
        self._n_features, self._evaluator, self._so_f = self._build(clf)

    def __getstate__(self):
        return dict(n_features=self._n_features, so_f=open(self._so_f).read())

    def __setstate__(self, state):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(state["so_f"])
        self._n_features = state["n_features"]
        self._so_f = tf.name
        self._evaluator = _compiled.CompiledPredictor(
            tf.name.encode("ascii"),
            cg.EVALUATE_FN_NAME.encode("ascii"))

    @classmethod
    def _build(cls, clf):
        if not cls.compilable(clf):
            raise ValueError("Predictor {} cannot be compiled".format(
                clf.__class__.__name__))

        lines = None
        n_features = None
        if isinstance(clf, DecisionTreeRegressor):
            n_features = clf.n_features_
            lines = cg.code_gen_tree(tree=clf.tree_)

        if isinstance(clf, GradientBoostingRegressor):
            n_features = clf.n_features

            # hack to get the initial (prior) on the decision tree.
            initial_value = clf._init_decision_function(
                np.zeros(shape=(1, n_features))).item((0, 0))

            lines = cg.code_gen_ensemble(
                trees=[e.tree_ for e in clf.estimators_.flat],
                individual_learner_weight=clf.learning_rate,
                initial_value=initial_value)

        if isinstance(clf, ForestRegressor):
            n_features = clf.n_features_
            lines = cg.code_gen_ensemble(
                trees=[e.tree_ for e in clf.estimators_],
                individual_learner_weight=1.0 / clf.n_estimators,
                initial_value=0.0)

        assert n_features is not None
        assert lines is not None

        so_f = cg.compile_code_to_object("\n".join(lines))
        evaluator = _compiled.CompiledPredictor(
            so_f.encode("ascii"),
            cg.EVALUATE_FN_NAME.encode("ascii"))
        return n_features, evaluator, so_f

    @classmethod
    def compilable(cls, clf):
        """
        Verifies that the given fitted model is eligible to be compiled.

        Returns True if the model is eligible, and False otherwise.

        Parameters
        ----------

        clf:
          A fitted regression tree/ensemble.


        """
        # TODO - is there an established way to check `is_fitted``?
        if isinstance(clf, DecisionTreeRegressor):
            return clf.n_outputs_ == 1 and clf.n_classes_ == 1 \
                and clf.tree_ is not None

        if isinstance(clf, GradientBoostingRegressor):
            return clf.estimators_.size and all(cls.compilable(e)
                                                for e in clf.estimators_.flat)

        if isinstance(clf, ForestRegressor):
            estimators = np.asarray(clf.estimators_)
            return estimators.size and all(cls.compilable(e)
                                           for e in estimators.flat)
        return False

    def predict(self, X):
        """Predict regression target for X.

        Parameters
        ----------
        X : array-like of shape = [n_samples, n_features]
            The input samples.

        Returns
        -------
        y: array of shape = [n_samples]
            The predicted values.
        """
        if X.dtype != DTYPE:
            raise ValueError("X.dtype is {}, not {}".format(X.dtype, DTYPE))
        if X.ndim != 2:
            raise ValueError(
                "Input must be 2-dimensional (n_samples, n_features), "
                "not {}".format(X.shape))

        n_samples, n_features = X.shape
        if self._n_features != n_features:
            raise ValueError("Number of features of the model must "
                             " match the input. Model n_features is {} and "
                             " input n_features is {}".format(
                                 self._n_features, n_features))

        result = np.empty(n_samples, dtype=DTYPE)
        return self._evaluator.predict(X, result)
