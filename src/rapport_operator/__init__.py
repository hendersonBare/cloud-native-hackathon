"""Rapport operator: a kopf controller that turns an Encounter into delegate Jobs, a Service and a NetworkPolicy.

Layout (one job per module):
  builders.py    pure functions that build the Kubernetes objects (SPEC 4.4)
  status.py      pure functions that derive the Encounter status from Job state (SPEC 4.4 "Status")
  config.py      the image and env passthrough the builders need, resolved once at startup
  kube.py        the only module that talks to the Kubernetes API (swappable with a fake in tests)
  controller.py  the reconcile logic, written against the KubeOps protocol
  handlers.py    thin kopf wrappers around the controller
  __main__.py    python -m rapport_operator
"""
