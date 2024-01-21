# activator-ghclient

![ci](https://github.com/jonathanalgar/activator-ghclient/actions/workflows/build-docker.yml/badge.svg)

![License: GPLv3](https://img.shields.io/badge/license-GPLv3-blue) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://makeapullrequest.com)

> :bulb: *Full demo:* https://github.com/jonathanalgar/docs-demo/pull/2

## Overview

Containerized GitHub action for interacting with the [activator](https://github.com/jonathanalgar/activator) service.

On a trigger comment in a pull request, the action sends the text of a supported file in a request to the [activator](https://github.com/jonathanalgar/activator) service for transformation. It then takes a response from the service, formats accordingly, and posts in-line suggestions or a block comment.

 ## Usage

First, create a new GitHub action workflow in your repo (eg. `.github/workflows/activator.yml`):

```yaml
name: activator

on:
  issue_comment:
    types:
      - created

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  activator-ghclient:
    runs-on: ubuntu-latest
    if: contains(github.event.comment.body, '/activator')
    container: 
      image: ghcr.io/jonathanalgar/activator-ghclient:latest
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    steps:
      - name: Add reaction to comment
        run: |
          COMMENT_ID=${{ github.event.comment.id }}
          curl -X POST -H "Authorization: token ${{ secrets.GITHUB_TOKEN }}" \
               -H "Content-Type: application/json" \
               -d '{"content":"eyes"}' \
               "https://api.github.com/repos/${{ github.repository }}/issues/comments/$COMMENT_ID/reactions"
      - name: Set ref for checkout
        id: set_ref
        run: |
          PR_API_URL="${{ github.event.issue.pull_request.url }}"
          REF=$(curl -s -H "Authorization: token ${{ secrets.GITHUB_TOKEN }}" $PR_API_URL | jq -r .head.ref)
          echo "REF=$REF" >> $GITHUB_ENV
      - name: Checkout
        uses: actions/checkout@v4.1.1
        with:
          fetch-depth: 1
          ref: ${{ env.REF }}

      - name: Run script
        env:
          GITHUB_REPOSITORY: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.issue.number }}
          ACTIVATOR_ENDPOINT: ${{ secrets.ACTIVATOR_ENDPOINT }}
          ACTIVATOR_TOKEN: ${{ secrets.ACTIVATOR_TOKEN }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          COMMENT_BODY: ${{ github.event.comment.body }}
          COMMENT_ID: ${{ github.event.comment.id }}
        run: python /app/activator-ghclient.py
```

You'll need to set the following repo secrets:

* `ACTIVATOR_ENDPOINT`: Endpoint URL of the running `activator` (eg. `https://activator-prod.westeurope.cloudapp.azure.com:9100/activator`)
* `ACTIVATOR_TOKEN`: Single token for service.

Once that's done you can comment `/activator /path/to/file.md` in a pull request to trigger the action.

## TODO

- [ ] Better error handling
- [ ] Unit tests
- [ ] Extend this TODO list