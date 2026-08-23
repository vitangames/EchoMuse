# Stamps the release version onto the image main already built and scanned.
#
# Used only by controller-release.yml. The controller image is built on every
# push to main and published by commit sha; the release promotes that exact
# image rather than rebuilding it, so what ships is what CI examined — a
# rebuild resolves floating base layers and unpinned wheels again, and what
# shipped was then never quite what was scanned.
#
# `docker buildx imagetools create` would be the natural promote and takes
# seconds, but it can only write manifest references — it cannot change an
# environment variable. EM_CONTROLLER_VERSION is baked at build time (ARG ->
# ENV in controller/Dockerfile) and the main build has no tag to bake, so it
# uses controller/config.yaml's `version:`. That is the GA pin, so promoting
# the same image as an Early Access release would ship a controller reporting
# the GA version: the dashboard header, the ESPHome project version, and every
# support bundle would name the wrong build.
#
# One layer setting one variable is the smallest thing that fixes it. Every
# application layer is still byte-for-byte what main built; only the
# environment differs, which is the one thing that genuinely cannot be known
# before the tag exists.
ARG BASE
FROM ${BASE}
ARG EM_CONTROLLER_VERSION
ENV EM_CONTROLLER_VERSION=${EM_CONTROLLER_VERSION}
