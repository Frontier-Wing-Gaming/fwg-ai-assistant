FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends asterisk build-essential pkg-config wget ca-certificates bzip2 patch python3 libsrtp2-dev libssl-dev libedit-dev uuid-dev libxml2-dev libsqlite3-dev libncurses-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /usr/src
RUN wget -q https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-20.21.0.tar.gz && wget -q https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-20.21.0.sha256 && sha256sum -c asterisk-20.21.0.sha256 && tar xzf asterisk-20.21.0.tar.gz
WORKDIR /usr/src/asterisk-20.21.0
RUN ./configure --prefix=/usr --libdir=/usr/lib --sysconfdir=/etc --localstatedir=/var --with-pjproject-bundled --with-jansson-bundled && make menuselect.makeopts && menuselect/menuselect --disable BUILD_NATIVE --disable-category MENUSELECT_CORE_SOUNDS --disable-category MENUSELECT_EXTRA_SOUNDS --disable-category MENUSELECT_MOH menuselect.makeopts && make -j2 && rm -rf /usr/lib/asterisk/modules && make install
WORKDIR /
CMD ["asterisk", "-f", "-vv"]
