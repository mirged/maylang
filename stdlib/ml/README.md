# Maylang ML

A dependency-free, pure-Maylang toolkit for small and medium tabular models.
It is designed to be readable and portable across Maylang's interpreter and
native compiler, not to replace optimized BLAS/GPU frameworks.

```may
import "random.may";
import "ml/nn.may";
import "ml/model.may";

let rng: Any = random_new(41);
let net: Any = nn_model();
nn_add_dense(net, 2, 8, "tanh", rng);
nn_add_dense(net, 8, 1, "sigmoid", rng);
let fit: Any = ml_fit(net, features, labels, 1500, 4,
                 ml_adam_default(0.03), rng, "binary_cross_entropy");
print(fit.history[len(fit.history) - 1]);
```

The package includes row-major tensors, shape-checked 2-D linear algebra,
NumPy-style trailing-dimension broadcasting and axis reductions, stable vector
and row-wise softmax, dense feed-forward networks, explicit backpropagation,
linear/ReLU/sigmoid/tanh/softmax activations, MSE and cross-entropy losses,
SGD with momentum, Adam, deterministic random streams, batching, train/test
splits, one-hot labels, feature scaling, accuracy, and JSON model snapshots.

## Modules

- `tensor.may` — dense tensors, reshape, reductions, transpose, dot, matmul,
  and stable vector softmax.
- `nn.may` — dense layers, forward/backward passes, prediction and snapshots.
  `nn_predict_one(model, row)` performs single-row inference without changing
  training caches or allocating intermediate product lists.
- `fixed.may` — typed, fixed-point dense controllers with softsign activation.
  `nn_fixed_model(dimensions, parameters, scale)` validates output-major weights
  and biases; `nn_fixed_predict(network, row)` accepts integer-scaled inputs
  and returns integer-scaled outputs. The scale is 1..32768, layer widths
  1..1024, and weights and inputs are bounded to ±16×scale for safe arithmetic.
- `loss.may` — MSE, binary/categorical cross entropy, gradients, confusion
  matrices, per-class precision/recall/F1, and accuracy.
- `optim.may` — SGD, momentum and Adam.
- `model.may` — minibatch `ml_fit`, evaluation and model persistence.
- `data.may` — deterministic splits, batches, one-hot labels and scaling.
- `classical.may` — k-nearest neighbors, k-means, linear and logistic regression.
- `../random.may` — seeded Park–Miller PRNG, shuffle, sampling and normal draws.

See `examples/ml_xor.may` for a complete training run, and
[Artificial Ecosystem](../../example_projects/simulations/ecosystem/README.md) for evolved neural
controllers and a reproducible 100,000-generation experiment.
