from src.evaluate import evaluate_model
from src.train_baseline import build_models


def test_v1_models_train_and_evaluate_offline():
    """Exercise the v1 model path without network access or committed artifacts."""
    titles = [
        "Economia chilena muestra nuevas senales de crecimiento",
        "Mercados locales cierran jornada con avances",
        "Astronomos observan una nueva region del espacio",
        "Cientificos estudian la formacion de estrellas",
    ]
    labels = ["economia", "economia", "ciencia", "ciencia"]
    expected_labels = ["ciencia", "economia"]

    for model in build_models().values():
        model.fit(titles, labels)
        metrics = evaluate_model(model, titles, labels, expected_labels)

        assert 0.0 <= metrics["accuracy"] <= 1.0
        assert 0.0 <= metrics["f1_macro"] <= 1.0
        assert set(metrics["per_class"]) == set(expected_labels)
        assert len(metrics["confusion_matrix"]) == len(expected_labels)
