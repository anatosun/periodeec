FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y git



ENV WORKDIR /app
ENV CONFIG /config
ENV HOME $CONFIG
ENV XDG_CONFIG_HOME $CONFIG
RUN mkdir -p $WORKDIR
RUN mkdir -p $CONFIG
WORKDIR $WORKDIR
COPY . $WORKDIR



ARG UNAME=periodeec
ENV PUID=1000
ENV PGID=1000
RUN groupadd -g $PGID -o $UNAME
RUN useradd -m -u $PUID -g $PGID -o -s /bin/bash $UNAME
RUN chown -R $PUID:$PGID $WORKDIR
RUN chown -R $PUID:$PGID $CONFIG

USER $UNAME

ENV PATH="${WORKDIR}/.venv/bin:$PATH"
RUN python -m venv .venv
RUN pip install -r requirements.txt
RUN pip install -e .
CMD ["periodeec"]
