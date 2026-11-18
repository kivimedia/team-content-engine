"""New backgrounds for a walking video (18-Nov): every other scene of a Creatorz render is
redrawn by a paid video model so the speaker seems to walk through different parts of their
village. Off unless the owner switches it on for one video.

This file stays empty of imports on purpose. The step runs under the Creatorz engine's own
Python (numpy, OpenCV, no TCE packages), so nothing here may pull in the app: the app side
lives in ``config``, everything else is plain standard library plus numpy and OpenCV.

  scenes   which stretches change (pure)
  looks    a workspace's set of places: a paragraph and a few background stills each
  omni     the paid model and the model that looks at its result
  clips    ffmpeg: cut a scene out, fit the result back to the exact frames
  checks   what a redrawn scene must pass before it is used
  step     the whole step for one render; ``cli.py`` is how the app starts it
  config   the app's side: settings, who has it, what a render is told
"""
