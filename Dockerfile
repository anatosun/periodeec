FROM python:3.11-rc-bullseye

RUN apt-get update && apt-get upgrade -y


ENV WORKDIR /config
ENV HOME $WORKDIR
ENV XDG_CONFIG_HOME $WORKDIR
RUN mkdir -p $WORKDIR
WORKDIR $WORKDIR
COPY . $WORKDIR
RUN pip install -r requirements.txt

CMD python3 "app.py"
