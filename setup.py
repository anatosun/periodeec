from setuptools import setup, find_packages

setup(
    name='periodeec',
    version='0.1.0',
    packages=find_packages(),
    description='Python cli utility to download your Spotify playlists.',
    author='Anatosun',
    author_email='z4jyol8l@duck.com',
    url='https://github.com/anatosun/periodeec',
    include_package_data=True,
    install_requires=[
        'requests',
        'schedule',
        'spotipy',
        'plexapi',
        'async-timeout',
    ],
    entry_points={
        'console_scripts': [
            'periodeec = periodeec.main:main',
        ],
    },
)
