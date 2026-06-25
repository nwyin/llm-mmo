#!/usr/bin/env python3
"""Post a Knowledge review comment on a PR, with a turn cap to avoid endless re-reviews.

Posts a new numbered comment each time (preserving history). `--count` returns how many
completed reviews already exist (used to enforce a max-turns budget); `--fetch-previous`
prints the latest review for follow-up context.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

SIGNATURE = "<!-- llm-mmo-review -->"
HEADING = "## Knowledge Review"


def github_api(method, url, token, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error: {e.code} {e.reason}", file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        raise


def find_reviews(repo, pr, token):
    reviews, page = [], 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}"
        comments = github_api("GET", url, token)
        if not comments:
            break
        reviews.extend(c for c in comments if SIGNATURE in c.get("body", ""))
        page += 1
    return reviews


def is_completed(comment):
    body = comment.get("body", "")
    return SIGNATURE in body and HEADING in body and "— Error" not in body


def post_comment(repo, pr, body, token):
    n = len(find_reviews(repo, pr, token)) + 1
    full = f"{SIGNATURE}\n**Knowledge Review #{n}**\n\n{body}"
    result = github_api("POST", f"https://api.github.com/repos/{repo}/issues/{pr}/comments", token, {"body": full})
    print(f"Posted Knowledge Review #{n} (comment {result.get('id')})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--token", required=True)
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--count", action="store_true")
    p.add_argument("--fetch-previous", action="store_true")
    args = p.parse_args()

    if args.count:
        print(sum(1 for c in find_reviews(args.repo, args.pr, args.token) if is_completed(c)))
        return
    if args.fetch_previous:
        completed = [c for c in find_reviews(args.repo, args.pr, args.token) if is_completed(c)]
        if completed:
            body = completed[-1]["body"]
            print(body[len(SIGNATURE) :].lstrip("\n") if body.startswith(SIGNATURE) else body)
        return

    if args.body_file:
        with open(args.body_file) as f:
            body = f.read().strip()
    else:
        body = (args.body or sys.stdin.read()).strip()
    if not body:
        print("No review body to post", file=sys.stderr)
        sys.exit(1)
    post_comment(args.repo, args.pr, body, args.token)


if __name__ == "__main__":
    main()
