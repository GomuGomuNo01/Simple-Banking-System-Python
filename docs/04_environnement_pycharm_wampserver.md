# 4. Environnement de travail : PyCharm et WampServer

## Choix de l'IDE : PyCharm (édition Professional)

Parmi les outils du pack JetBrains, **PyCharm Professional** couvre à lui seul tout le projet :

| Besoin | Fonctionnalité PyCharm |
|---|---|
| Python | Éditeur, environnement virtuel, exécution et débogage |
| SQL et MySQL | Outil **Database** intégré (même moteur que DataGrip) : connexion, exécution de scripts, autocomplétion sur le schéma, diagrammes |
| Notebooks | Support Jupyter intégré |
| Tests | Lancement de pytest avec affichage des résultats |
| Git et GitHub | Commits, branches, historique, comparaison de fichiers, push |
| Documentation | Aperçu Markdown avec diagrammes Mermaid |

DataGrip ferait double emploi pour le SQL, et utiliser deux IDE compliquerait le projet sans bénéfice. Les fonctionnalités Database et Jupyter nécessitent l'édition Professional, incluse dans le pack JetBrains.

## 1. Préparer MySQL avec WampServer

1. Lancer WampServer et attendre que l'icône devienne **verte**.
2. Vérifier la version et le port : clic gauche sur l'icône, **MySQL**, puis **Version** et **Port utilisé par MySQL**. Le projet a été développé avec MySQL 9.6 sur le port **3306** (MySQL 8.0 ou plus récent est nécessaire pour les CTE et les fonctions de fenêtre).
3. Par défaut, l'utilisateur `root` n'a pas de mot de passe. Si tu en as défini un, il faudra le reporter dans le fichier `.env` (étape 3).

Si MariaDB est aussi installé, il écoute souvent sur le port 3307 : ne pas confondre les deux.

## 2. Ouvrir le projet et configurer Python

1. **File, Open**, puis sélectionner le dossier du projet.
2. **Settings, Project, Python Interpreter, Add Interpreter, Add Local Interpreter**.
3. Choisir **Virtualenv Environment**, **Existing** si le dossier `.venv` existe déjà, sinon **New** avec Python 3.12.
4. Ouvrir le terminal intégré (**View, Tool Windows, Terminal**) et installer les dépendances :

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

La seconde commande installe le package `sbs_bank` en mode éditable : le code de `src/` est importable depuis les scripts, les tests et le notebook.

## 3. Configurer la connexion à la base

Copier `.env.example` en `.env` et adapter si nécessaire. Le fichier `.env` est ignoré par Git : il ne doit jamais être publié.

```bash
copy .env.example .env
```

## 4. Connecter l'outil Database de PyCharm

1. **View, Tool Windows, Database**, puis **+, Data Source, MySQL**.
2. Host `localhost`, Port `3306`, User `root`, mot de passe vide (ou le tien).
3. Si PyCharm le propose, cliquer sur **Download missing driver files**.
4. **Test Connection**, puis **OK**.
5. Après avoir lancé le pipeline (étape 5), sélectionner la base `sbs_bank` dans l'onglet **Schemas** de la source de données.

Pour exécuter un fichier SQL : l'ouvrir, choisir la source `sbs_bank` en haut à droite de l'éditeur, placer le curseur dans une requête et utiliser **Ctrl+Entrée**. Clic droit sur la base, **Diagrams, Show Diagram** affiche le modèle relationnel.

## 5. Construire la base et les données

```bash
python -m sbs_bank.pipeline all
```

Durée : environ 1 à 2 minutes. Le pipeline génère les fichiers dans `data/raw/`, recrée la base `sbs_bank`, nettoie les clients, charge les tables, crée les vues et écrit `reports/data_quality_report.md`.

## 6. Lancer les tests

```bash
python -m pytest
```

Les tests d'intégration créent puis suppriment une base temporaire `sbs_bank_test`. Ils sont ignorés si WampServer n'est pas démarré.

## 7. Utiliser l'application bancaire

```bash
python -m sbs_bank.cli
```

Dans le terminal intégré, le code PIN est saisi de façon masquée. Dans la console **Run** de PyCharm, qui n'est pas un vrai terminal, l'application bascule automatiquement sur une saisie visible pour ne pas se bloquer.

## 8. Ouvrir le notebook

Ouvrir `notebooks/analyse_activite_sbs_bank.ipynb`, sélectionner l'interpréteur `.venv` comme noyau et exécuter les cellules (**Run All**). Pour régénérer toutes les sorties en ligne de commande :

```bash
jupyter nbconvert --to notebook --execute --inplace notebooks/analyse_activite_sbs_bank.ipynb
```

## 9. Git dans PyCharm

- Vérifier la branche active en bas à droite de la fenêtre : elle doit être `dev`.
- **Commit** (Ctrl+K) : relire la liste des fichiers cochés avant de valider. Ni `.venv/`, ni `.env`, ni `data/raw/` ne doivent apparaître (ils sont exclus par `.gitignore`).
- **Push** (Ctrl+Shift+K) pour publier la branche sur GitHub.
- L'identité Git utilisée pour les commits se vérifie avec `git config user.name` et `git config user.email`.
