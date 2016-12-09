# vi: set ft=dockerfile :


FROM decapod-controller
MAINTAINER Sergey Arkhipov <sarkhipov@mirantis.com>


LABEL description="Different cron jobs for Decapod" version="0.2.0" vendor="Mirantis"


COPY backend/monitoring                    /project/monitoring
COPY containerization/files/crontab        /decapod
COPY containerization/files/cron-caddyfile /etc/caddy/config


RUN set -x \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
    cron \
    curl \
    gcc \
    python-dev \
    python-pip \
  && pip2 install --no-cache-dir /project/monitoring \
  && curl --silent --show-error --fail --location \
    --header "Accept: application/tar+gzip, application/x-gzip, application/octet-stream" -o - \
    "https://caddyserver.com/download/build?os=linux&arch=amd64&features=" | \
    tar --no-same-owner -C /usr/bin/ -xz caddy \
  && chmod 0755 /usr/bin/caddy \
  && mkdir -p /www \
  && cat /decapod | crontab - \
  && mkfifo /var/log/cron.log \
  && rm -r /decapod /project \
  && apt-get clean \
  && apt-get purge -y gcc python-dev python-pip curl \
  && apt-get autoremove -y \
  && rm -r /var/lib/apt/lists/*


EXPOSE 8000

CMD ["dockerize", "-wait", "tcp://database:27017", "--", "sh", "-c", "caddy -conf '/etc/caddy/config' & cron && tail -F /var/log/cron.log"]
