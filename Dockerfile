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
RUN pip install -r requirements.txt
CMD python3 "app.py"
