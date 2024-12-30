import os.path
from setuptools import find_packages, setup

dirname = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(dirname, "README.md")) as f:
    long_description = f.read()

setup(name="sensorpush-ha",
      version="1.1.0",
      description="SensorPush Cloud Home Assistant Library",
      long_description=long_description,
      long_description_content_type="text/markdown",
      author="Steven Stallion",
      author_email="sstallion@gmail.com",
      url="https://github.com/sstallion/sensorpush-ha",
      packages=find_packages(),
      classifiers=[
          "Development Status :: 5 - Production/Stable",
          "Environment :: Web Environment",
          "Intended Audience :: Developers",
          "License :: OSI Approved :: BSD License",
          "Operating System :: OS Independent",
          "Programming Language :: Python",
          "Programming Language :: Python :: 3",
          "Programming Language :: Python :: 3.12",
          "Programming Language :: Python :: 3.13",
          "Topic :: Internet :: WWW/HTTP",
          "Topic :: Software Development :: Libraries",
          "Topic :: Software Development :: Libraries :: Python Modules",
      ],
      license="BSD-2-Clause",
      keywords="homeassistant sensorpush",
      package_data={"sensorpush_ha": ["py.typed"]},
      install_requires=[
          "sensorpush-api>=2.1.0",
      ],
      extras_require={
          "release": [
              "build>=0.3.0",
          ]
      })
