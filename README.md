# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/taskinen/yle-dl-plex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                              |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|---------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/yle\_dl\_plex/\_\_init\_\_.py |        1 |        0 |        0 |        0 |    100% |           |
| src/yle\_dl\_plex/\_\_main\_\_.py |        3 |        3 |        2 |        0 |      0% |       1-4 |
| src/yle\_dl\_plex/areena.py       |      132 |        2 |       50 |        2 |     98% |  101, 174 |
| src/yle\_dl\_plex/cli.py          |      226 |      123 |       82 |        2 |     43% |66-71, 75-93, 102, 126-129, 221-\>220, 240-253, 269-306, 314-339, 348-374, 378-450, 454 |
| src/yle\_dl\_plex/nfo.py          |       61 |        0 |        6 |        0 |    100% |           |
| src/yle\_dl\_plex/yledl.py        |       47 |       15 |        2 |        0 |     65% |67-78, 86-88, 101-105 |
| **TOTAL**                         |  **470** |  **143** |  **142** |    **4** | **67%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/taskinen/yle-dl-plex/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/taskinen/yle-dl-plex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/taskinen/yle-dl-plex/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/taskinen/yle-dl-plex/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Ftaskinen%2Fyle-dl-plex%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/taskinen/yle-dl-plex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.