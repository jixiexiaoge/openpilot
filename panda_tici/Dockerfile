FROM ubuntu:24.04

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/tmp/pythonpath

# deps install
COPY pyproject.toml __init__.py setup.sh /tmp/
COPY python/__init__.py /tmp/python/
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends sudo && /tmp/setup.sh

COPY pyproject.toml __init__.py $PYTHONPATH/panda_tici/
COPY python/__init__.py $PYTHONPATH/panda_tici/python/
RUN pip3 install --break-system-packages --no-cache-dir $PYTHONPATH/panda_tici/[dev]

RUN git config --global --add safe.directory $PYTHONPATH/panda_tici

# for Jenkins
COPY README.md panda_tici.tar.* /tmp/
RUN mkdir -p /tmp/pythonpath/panda_tici && \
    tar -xvf /tmp/panda_tici.tar.gz -C /tmp/pythonpath/panda_tici/ || true
