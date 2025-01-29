# Contributing

We welcome all contributions, bug reports, and suggestions!

## Installing the development version

To install the latest version from this repository, follow these steps:

-   Clone this repository using `git clone`.

```console
$ git clone https://github.com/cartodb/carto-qgis-plugin.git
```

-   Create a link between the repository folder and the QGIS 3 plugins folder.

```console
$ cd carto-qgis-plugin
$ python helper.py install
```

-   Start QGIS and you will find the plugin in the plugins menu. If it's not available yet, activate
    it in the QGIS Plugin Manager.

## Packaging

To package the plugin, suitable for installing into QGIS:

```console
$ python helper.py package
```

A `carto.zip` file is generated in the repo root.

## Code formatting

We use [Black](https://github.com/psf/black) to ensure consistent code formatting. We recommend integrating black with your editor:

-   Sublime Text: install [sublack](https://packagecontrol.io/packages/sublack) via Package Control
-   VSCode [instructions](https://code.visualstudio.com/docs/python/editing#_formatting)

We use the default settings, and target python 3.7+.

One easy solution is to install [pre-commit](https://pre-commit.com), run `pre-commit install --install-hooks` and it'll automatically validate your changes code as a git pre-commit hook.
