# Copyright (C) 2015-2020 Regents of the University of California
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import textwrap

applianceSelf = os.environ['TOIL_APPLIANCE_SELF']
sdistName = os.environ['_TOIL_SDIST_NAME']

# Make sure to install packages into the pip for the version of Python we are
# building for.
python = f'python{sys.version_info[0]}.{sys.version_info[1]}'
pip = f'{python} -m pip'


dependencies = ' '.join(['libffi-dev',  # For client side encryption for extras with PyNACL
                         python,
                         f'{python}-dev',
                         'python3.8-distutils' if python == 'python3.8' else '',
                         'python3.9-distutils' if python == 'python3.9' else '',
                         # 'python3.9-venv' if python == 'python3.9' else '',
                         'python3-pip',
                         'libcurl4-openssl-dev',
                         'libssl-dev',
                         'wget',
                         'curl',
                         'openssh-server',
                         "nodejs",  # CWL support for javascript expressions
                         'rsync',
                         'screen',
                         'build-essential',  # We need a build environment to build Singularity 3.
                         'libarchive13',
                         'libc6',
                         'libseccomp2',
                         'e2fsprogs',
                         'uuid-dev',
                         'libgpgme11-dev',
                         'libseccomp-dev',
                         'pkg-config',
                         'squashfs-tools',
                         'cryptsetup',
                         'less',
                         'vim',
                         'git'])


def heredoc(s):
    s = textwrap.dedent(s).format(**globals())
    return s[1:] if s.startswith('\n') else s


motd = heredoc('''

    This is the Toil appliance. You can run your Toil script directly on the appliance.
    Run toil <workflow>.py --help to see all options for running your workflow.
    For more information see http://toil.readthedocs.io/en/latest/

    Copyright (C) 2015-2020 Regents of the University of California

    Version: {applianceSelf}

''')

# Prepare motd to be echoed in the Dockerfile using a RUN statement that uses bash's print
motd = ''.join(l + '\\n\\\n' for l in motd.splitlines())

print(heredoc('''
    # We can't use a newer Ubuntu until we no longer need Mesos
    FROM ubuntu:16.04

    ARG TARGETARCH

    # make sure we don't use too new a version of setuptools (which can get out of sync with poetry and break things)
    ENV SETUPTOOLS_USE_DISTUTILS=stdlib

    RUN apt-get -y update --fix-missing && apt-get -y upgrade && apt-get -y install apt-transport-https ca-certificates software-properties-common && apt-get clean && rm -rf /var/lib/apt/lists/*

    RUN echo "deb http://repos.mesosphere.io/ubuntu/ xenial main" \
        > /etc/apt/sources.list.d/mesosphere.list \
        && apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF \
        && echo "deb http://deb.nodesource.com/node_6.x xenial main" \
        > /etc/apt/sources.list.d/nodesource.list \
        && apt-key adv --keyserver keyserver.ubuntu.com --recv 68576280

    RUN add-apt-repository -y ppa:deadsnakes/ppa

    RUN apt-get -y update --fix-missing && \
        DEBIAN_FRONTEND=noninteractive apt-get -y upgrade && \
        DEBIAN_FRONTEND=noninteractive apt-get -y install {dependencies} && \
        if [ $TARGETARCH = amd64 ] ; then DEBIAN_FRONTEND=noninteractive apt-get -y install mesos=1.0.1-2.0.94.ubuntu1604 ; fi && \
        apt-get clean && \
        rm -rf /var/lib/apt/lists/*

    # Install a particular old Debian Sid Singularity from somewhere.
    # The dependencies it thinks it needs aren't really needed and aren't
    # available here.
    ADD singularity-sources.tsv /etc/singularity/singularity-sources.tsv
    RUN wget "$(cat /etc/singularity/singularity-sources.tsv | grep "^$TARGETARCH" | cut -f3)" && \
        (dpkg -i singularity-container_3*.deb || true) && \
        dpkg --force-depends --configure -a && \
        sed -i 's/containernetworking-plugins, //' /var/lib/dpkg/status && \
        sed -i 's!bind path = /etc/localtime!#bind path = /etc/localtime!g' /etc/singularity/singularity.conf && \
        mkdir -p /usr/local/libexec/toil && \
        mv /usr/bin/singularity /usr/local/libexec/toil/singularity-real \
        && /usr/local/libexec/toil/singularity-real version

    RUN mkdir /root/.ssh && \
        chmod 700 /root/.ssh

    ADD waitForKey.sh /usr/bin/waitForKey.sh

    ADD customDockerInit.sh /usr/bin/customDockerInit.sh

    ADD singularity-wrapper.sh /usr/local/bin/singularity

    RUN chmod 777 /usr/bin/waitForKey.sh && chmod 777 /usr/bin/customDockerInit.sh && chmod 777 /usr/local/bin/singularity

    # fixes an incompatibility updating pip on Ubuntu 16 w/ python3.8
    RUN sed -i "s/platform.linux_distribution()/('Ubuntu', '16.04', 'xenial')/g" /usr/lib/python3/dist-packages/pip/download.py

    # The stock pip is too old and can't install from sdist with extras
    RUN {pip} install --upgrade pip==21.3.1

    # Default setuptools is too old
    RUN {pip} install --upgrade setuptools==59.7.0

    # Include virtualenv, as it is still the recommended way to deploy pipelines
    RUN {pip} install --upgrade virtualenv==20.0.17

    # Install s3am (--never-download prevents silent upgrades to pip, wheel and setuptools)
    RUN virtualenv --python {python} --never-download /home/s3am \
        && /home/s3am/bin/pip install s3am==2.0 \
        && ln -s /home/s3am/bin/s3am /usr/local/bin/

    # Install statically linked version of docker client
    RUN curl https://download.docker.com/linux/static/stable/$(if [ $TARGETARCH = amd64 ] ; then echo x86_64 ; else echo aarch64 ; fi)/docker-18.06.1-ce.tgz \
        | tar -xvzf - --transform='s,[^/]*/,,g' -C /usr/local/bin/ \
        && chmod u+x /usr/local/bin/docker \
        && /usr/local/bin/docker -v

    # Fix for Mesos interface dependency missing on ubuntu
    RUN {pip} install protobuf==3.0.0

    # Fix for https://issues.apache.org/jira/browse/MESOS-3793
    ENV MESOS_LAUNCHER=posix

    # Fix for `screen` (https://github.com/BD2KGenomics/toil/pull/1386#issuecomment-267424561)
    ENV TERM linux

    # Run bash instead of sh inside of screen
    ENV SHELL /bin/bash
    RUN echo "defshell -bash" > ~/.screenrc

    # An appliance may need to start more appliances, e.g. when the leader appliance launches the
    # worker appliance on a worker node. To support this, we embed a self-reference into the image:
    ENV TOIL_APPLIANCE_SELF {applianceSelf}

    RUN mkdir /var/lib/toil
    ENV TOIL_WORKDIR /var/lib/toil

    # We want to get binaries mounted in from the environemnt on Toil-managed Kubernetes
    env PATH /opt/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

    # We want to pick the right Python when the user runs it
    RUN rm /usr/bin/python3 && rm /usr/bin/python && \
        ln -s /usr/bin/{python} /usr/bin/python3 && \
        ln -s /usr/bin/python3 /usr/bin/python

    # This component changes most frequently and keeping it last maximizes Docker cache hits.
    COPY {sdistName} .
    RUN {pip} install {sdistName}[all]
    RUN rm {sdistName}

    # We intentionally inherit the default ENTRYPOINT and CMD from the base image, to the effect
    # that the running appliance just gives you a shell. To start the Mesos daemons, the user
    # should override the entrypoint via --entrypoint.

    RUN echo '[ ! -z "$TERM" -a -r /etc/motd ] && cat /etc/motd' >> /etc/bash.bashrc \
        && printf '{motd}' > /etc/motd
'''))
