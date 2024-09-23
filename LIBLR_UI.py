import sys
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
import numpy as np
import pandas as pd

from LIBLR import *

class ParserUI(QMainWindow):
    def __init__(self):
        super(ParserUI, self).__init__()

        self.setWindowTitle('Parser')
        # self.showMaximized()

        self.initUi()

    def initUi(self):
        gLayout = QGridLayout()

        # (0, 0) , (0, 1)
        # (1, 0) , (1, 1)
        gLayout.addWidget(self.createFunction(), 0, 0)
        gLayout.addWidget(self.createText(), 0, 1)
        gLayout.addWidget(self.createGrammar(), 0, 2)
        gLayout.addWidget(self.createSet(), 0, 3)
        gLayout.addWidget(self.createParser(), 1, 0, 1, 4)

        main_widget = QWidget()
        main_widget.setLayout(gLayout)
        self.setCentralWidget(main_widget)

    def createFunction(self):
        groupBox = QGroupBox('Function')
        self.pb_open = QPushButton('Open File')
        self.pb_clear = QPushButton('Clear')
        self.pb_process = QPushButton('Process')
        self.pb_LRtable = QPushButton('LR Table')
        self.pb_state = QPushButton('State')

        self.pb_open.clicked.connect(lambda: self.FileOpened())
        self.pb_clear.clicked.connect(lambda: self.GrammarCleared())
        self.pb_process.clicked.connect(lambda: self.Process())
        self.pb_LRtable.clicked.connect(lambda: self.LRTableGenerated())
        self.pb_state.clicked.connect(lambda: self.State())

        vLayout = QVBoxLayout()
        vLayout.setAlignment(Qt.AlignTop)
        vLayout.addWidget(self.pb_open)
        vLayout.addWidget(self.pb_clear)
        vLayout.addWidget(self.pb_process)
        vLayout.addWidget(self.pb_LRtable)
        vLayout.addWidget(self.pb_state)
        groupBox.setLayout(vLayout)
        return groupBox

    def createText(self):
        groupBox = QGroupBox('Text')
        self.te_text = QTextEdit()

        vLayout = QVBoxLayout()
        vLayout.addWidget(self.te_text)
        groupBox.setLayout(vLayout)
        return groupBox

    def createGrammar(self):
        groupBox = QGroupBox('Grammar')
        self.te_grammar = QTextEdit()

        vLayout = QVBoxLayout()
        vLayout.addWidget(self.te_grammar)
        groupBox.setLayout(vLayout)
        return groupBox

    def createParser(self):
        w_parser = QWidget()
        self.pb_parse = QPushButton('Parse')
        self.le_parser = QLineEdit()

        self.pb_parse.clicked.connect(lambda: self.Parse())

        hLayout = QHBoxLayout()
        hLayout.addWidget(self.pb_parse)
        hLayout.addWidget(self.le_parser)
        w_parser.setLayout(hLayout)
        return w_parser

    def createSet(self):
        groupBox = QGroupBox('First & Follow')
        self.tv_set = QTableView()

        vLayout = QVBoxLayout()
        vLayout.addWidget(self.tv_set)
        groupBox.setLayout(vLayout)
        return groupBox

    def GrammarCleared(self):
        self.te_text.clear()
        self.te_grammar.clear()
        self.model_set.clearView()
        self.grammar = None
        self.grammar_analyzer = None

    def Parse(self):
        text = self.le_parser.text()
        parser = create_parser(self.te_text.toPlainText(), algorithm = 'lr1')
        result = parser(text)
        print(result)

    def State(self):
        self.state = State()
        self.state.show()

    def Process(self):
        text = self.te_text.toPlainText()
        self.grammar = load_from_string(text)
        self.grammar_analyzer = GrammarAnalyzer(self.grammar)
        self.grammar_analyzer.process()
        self.te_grammar.clear()
        self.te_grammar.insertPlainText(self.grammar.print())
        self.setUpdated(self.grammar_analyzer.print_first())

    def FileOpened(self, file_name=None):
        if not file_name:
            file_name, file_type = QFileDialog.getOpenFileName(self, "Open File", "./", "All Files(*);;EBNF(*.ebnf);;Text (*.txt)")
            if not file_name:
                return
        self.te_text.clear()
        with open(file_name, 'r') as r_grammar:
            self.te_text.insertPlainText(r_grammar.read())
        self.Process()

    def setUpdated(self, table):
        font = self.tv_set.horizontalHeader().font()
        font.setBold(True)
        self.tv_set.horizontalHeader().setFont(font)

        df = pd.DataFrame(table[1:], columns=table[0])
        self.model_set = PDTable(df)
        self.tv_set.setModel(self.model_set)

    def LRTableGenerated(self):
        self.lr1 = LR1Analyzer(self.grammar)
        self.lr1.process()

        self.lr_table = Table(self.lr1.tab.print())
        self.lr_table.show()

class State(QWidget):
    def __init__(self):
        super().__init__()

class Table(QWidget):
    def __init__(self, table):
        super().__init__()
        self.setWindowTitle('LR1 Table')
        self.tv_table = QTableView()

        font = self.tv_table.horizontalHeader().font()
        font.setBold(True)
        self.tv_table.horizontalHeader().setFont(font)

        df = pd.DataFrame(table[1:], columns=table[0])
        model = PDTable(df)
        self.tv_table.setModel(model)

        vLayout = QVBoxLayout()
        vLayout.addWidget(self.tv_table)
        self.setLayout(vLayout)

        self.resize(self.tv_table.width(), self.tv_table.height())


class PDTable(QAbstractTableModel):
    def __init__(self, data):
        QAbstractTableModel.__init__(self)
        self._data = data

    def rowCount(self, parent=None):
        return self._data.shape[0]

    def columnCount(self, parent=None):
        return self._data.shape[1]

    # 显示数据
    def data(self, index, role=Qt.DisplayRole):
        if index.isValid():
            if role == Qt.DisplayRole:
                return str(self._data.iloc[index.row(), index.column()])
        return None

    # 显示行和列头
    def headerData(self, col, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._data.columns[col]
        elif orientation == Qt.Vertical and role == Qt.DisplayRole:
            return self._data.axes[0][col]
        return None

    def removeRows(self, row, count, parent):
        self.beginRemoveRows(QModelIndex(), 0, row + count - 1)
        for i in range(count):
            self._data.drop(row + count - 1 - i, inplace=True)     # 倒着删
        self.endRemoveRows()

    def clearView(self):
        self.removeRows(0, self.rowCount(), QModelIndex())


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ui = ParserUI()
    ui.show()
    ui.FileOpened('.\\grammar\\func.ebnf')
    sys.exit(app.exec())