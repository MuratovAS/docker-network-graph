FROM python:3-alpine

WORKDIR /usr/src/app
ENV PIP_ROOT_USER_ACTION=ignore

COPY Pipfile Pipfile.lock ./

RUN pip install pipenv
# RUN pipenv lock
RUN pipenv install --system --deploy

COPY docker-network-graph.py ./

ENTRYPOINT ["python", "docker-network-graph.py"]
