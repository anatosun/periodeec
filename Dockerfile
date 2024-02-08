FROM python:3.11-rc-bullseye

RUN apt-get update && apt-get upgrade -y 


ENV WORKDIR /app
ENV CONFIG /config
ENV HOME $CONFIG
ENV XDG_CONFIG_HOME $CONFIG
RUN mkdir -p $WORKDIR
RUN mkdir -p $CONFIG
WORKDIR $WORKDIR
COPY . $WORKDIR



ARG UNAME=abc
ARG PUID=1000
ARG PGID=1000
RUN groupadd -g $PGID -o $UNAME
RUN useradd -m -u $PUID -g $PGID -o -s /bin/bash $UNAME
RUN chown -R $PUID:$PGID $WORKDIR
RUN chown -R $PUID:$PGID $CONFIG

USER $UNAME

ENV PATH="${WORKDIR}/.env/bin:$PATH"
ENV PATH="${CONFIG}/local/bin:$PATH"
RUN python -m venv .venv
RUN pip install -r requirements.txt
CMD python "app.py"
