# Reference context

Markdown files here are added to the interviewer's instructions at the start of every live interview, as guidance on what strong answers look like at each stage. The interviewer uses them to judge and to decide what to probe. It is told never to quote them or coach from them during the interview.

- Every `.md` file in this folder and its subfolders is loaded in alphabetical order by path. README files are skipped.
- The web server reads the folder fresh for each interview, so edits take effect without a restart. The setup page lists the files it found.
- An empty folder is fine. The interviewer then judges from the built-in rubric in `interview.py`.
- Interview results are saved as JSON in `private/progress/`. Only `.md` files are loaded, so results never become reference material; the interviewer gets a short summary of them instead.

## Public and private context

This repository is public. Put material you wrote yourself directly in this folder.

Put anything that isn't yours to publish, such as course notes, blog or book excerpts, or an employer's interview guide, in `private/`. This repository ignores that folder. The maintainer keeps it as a separate private repository, cloned into place:

```sh
git clone https://github.com/<you>/<your-private-context-repo>.git context/private
```

Without that private repository, the agent still works; it just has less reference material.

## Cost

These files are resent with every turn of an interview. They are marked for prompt caching, so after the first turn they are read from the cache at a fraction of the normal price. Even so, large files make every interview slower and more expensive. A few focused pages work better than a whole course.
